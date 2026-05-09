"""
PDF Parser & Intelligence API
------------------------------
Extract text, metadata, tables, and structured content from any PDF.
Accepts PDFs via URL or direct file upload — no API key required for the
PDF source.

Endpoints
  POST /extract-text          Full text extraction (page-by-page)
  POST /metadata              Title, author, page count, encryption status
  POST /pages                 Extract specific page range as text
  POST /tables                Extract tables (returns array of rows per table)
  POST /search                Search a keyword/phrase, return matches with pages
  POST /word-count            Words, characters, pages
  POST /info                  Quick info: pages, size, encrypted, has-text

Input formats (any endpoint):
  - JSON body:        {"url": "https://example.com/file.pdf"}
  - Form upload:      file=@/path/to/file.pdf
"""
import io
import os
import re
import sys
import time
import asyncio
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from fastapi import FastAPI, HTTPException, Depends, Query, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field, AnyHttpUrl

import pypdf
import pdfplumber

from common.auth import verify_rapidapi_request
from common.response import success


# ---------------------------------------------------------------------------
# Configuration / limits
# ---------------------------------------------------------------------------
MAX_PDF_BYTES = 25 * 1024 * 1024           # 25 MB hard cap on PDF size
MAX_PAGES_TEXT = 500                       # Cap pages we'll text-extract
MAX_PAGES_TABLES = 100                     # pdfplumber is slower → tighter cap
HTTP_TIMEOUT = 20.0
USER_AGENT = "PDFParserAPI/1.0"

_executor = ThreadPoolExecutor(max_workers=10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _executor.shutdown(wait=False)


app = FastAPI(
    title="PDF Parser & Intelligence API",
    description=(
        "Extract text, metadata, tables, and structured content from any PDF. "
        "Supports both URL fetching and direct file uploads. "
        "Built for document automation, RAG pipelines, search indexing, and data extraction tools."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# PDF source resolution
# ---------------------------------------------------------------------------
class UrlBody(BaseModel):
    url: AnyHttpUrl = Field(..., description="Public URL pointing to a PDF file")


async def _fetch_url(url: str) -> bytes:
    """Download a PDF from a remote URL with size enforcement."""
    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*;q=0.5"},
        ) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to fetch PDF: HTTP {resp.status_code}",
                    )
                # Honor Content-Length when present
                cl = resp.headers.get("content-length")
                if cl and int(cl) > MAX_PDF_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"PDF exceeds {MAX_PDF_BYTES // (1024 * 1024)} MB limit",
                    )
                buf = bytearray()
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    buf.extend(chunk)
                    if len(buf) > MAX_PDF_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"PDF exceeds {MAX_PDF_BYTES // (1024 * 1024)} MB limit",
                        )
                data = bytes(buf)
    except HTTPException:
        raise
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Network error fetching PDF: {e}")
    if not data:
        raise HTTPException(status_code=400, detail="Downloaded file is empty")
    return data


async def _resolve_pdf(
    file: Optional[UploadFile],
    url: Optional[str],
) -> bytes:
    """Resolve PDF bytes from either upload or URL. Validates size + type."""
    if file is None and not url:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'file' (upload) or 'url' (form field / JSON body).",
        )
    if file is not None:
        # Read the upload
        data = await file.read()
        if len(data) > MAX_PDF_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"PDF exceeds {MAX_PDF_BYTES // (1024 * 1024)} MB limit",
            )
        if not data:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        return data
    return await _fetch_url(str(url))


def _is_pdf(data: bytes) -> bool:
    """Quick magic-byte check for PDF signature."""
    return data[:4] == b"%PDF"


def _run_sync(fn, *args, **kwargs):
    """Run a blocking PDF op in the thread pool."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))


# ---------------------------------------------------------------------------
# Blocking PDF helpers (run via _run_sync)
# ---------------------------------------------------------------------------
def _open_pypdf(data: bytes) -> pypdf.PdfReader:
    reader = pypdf.PdfReader(io.BytesIO(data))
    return reader


def _safe_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    try:
        return str(v)
    except Exception:
        return None


def _extract_metadata(data: bytes) -> Dict[str, Any]:
    reader = _open_pypdf(data)
    info = reader.metadata or {}
    # pypdf returns IndirectObject keys, normalize them
    meta = {}
    for k, v in info.items() if hasattr(info, "items") else []:
        key = k.lstrip("/").lower() if isinstance(k, str) else str(k)
        meta[key] = _safe_str(v)
    return {
        "page_count": len(reader.pages),
        "encrypted": reader.is_encrypted,
        "title": meta.get("title"),
        "author": meta.get("author"),
        "subject": meta.get("subject"),
        "keywords": meta.get("keywords"),
        "creator": meta.get("creator"),
        "producer": meta.get("producer"),
        "creation_date": meta.get("creationdate"),
        "modification_date": meta.get("moddate"),
        "raw": meta,
    }


def _extract_text(data: bytes, page_start: int = 1, page_end: Optional[int] = None) -> Dict[str, Any]:
    reader = _open_pypdf(data)
    if reader.is_encrypted:
        # Best-effort try with empty password
        try:
            reader.decrypt("")
        except Exception:
            raise HTTPException(status_code=400, detail="PDF is encrypted; cannot extract text")
    total = len(reader.pages)
    end = page_end or total
    start = max(1, page_start)
    end = min(end, total, start + MAX_PAGES_TEXT - 1)
    if start > total:
        raise HTTPException(status_code=400, detail=f"page_start {start} > total pages {total}")

    pages_out = []
    full_text_parts = []
    for idx in range(start - 1, end):
        try:
            t = reader.pages[idx].extract_text() or ""
        except Exception:
            t = ""
        pages_out.append({"page": idx + 1, "text": t, "char_count": len(t)})
        full_text_parts.append(t)

    full_text = "\n\n".join(full_text_parts)
    return {
        "page_count": total,
        "page_range": {"start": start, "end": end},
        "pages": pages_out,
        "text": full_text,
        "char_count": len(full_text),
        "word_count": len(full_text.split()),
    }


def _extract_tables(data: bytes, page_start: int = 1, page_end: Optional[int] = None) -> Dict[str, Any]:
    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        total = len(pdf.pages)
        end = page_end or total
        start = max(1, page_start)
        end = min(end, total, start + MAX_PAGES_TABLES - 1)
        if start > total:
            raise HTTPException(status_code=400, detail=f"page_start {start} > total pages {total}")
        for idx in range(start - 1, end):
            page = pdf.pages[idx]
            try:
                page_tables = page.extract_tables() or []
            except Exception:
                page_tables = []
            for t_idx, tbl in enumerate(page_tables):
                # Coerce all cells to str for JSON safety
                rows = [[("" if c is None else str(c)) for c in row] for row in tbl]
                out.append({
                    "page": idx + 1,
                    "table_index": t_idx,
                    "row_count": len(rows),
                    "col_count": max((len(r) for r in rows), default=0),
                    "rows": rows,
                })
    return {
        "page_count": total,
        "table_count": len(out),
        "tables": out,
    }


def _search_pdf(data: bytes, query: str, case_sensitive: bool = False) -> Dict[str, Any]:
    if not query or len(query.strip()) < 1:
        raise HTTPException(status_code=400, detail="query must be at least 1 character")

    reader = _open_pypdf(data)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise HTTPException(status_code=400, detail="PDF is encrypted; cannot search")

    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(query), flags)

    matches = []
    total_pages = len(reader.pages)
    pages_to_scan = min(total_pages, MAX_PAGES_TEXT)
    for idx in range(pages_to_scan):
        try:
            text = reader.pages[idx].extract_text() or ""
        except Exception:
            text = ""
        page_matches = list(pattern.finditer(text))
        for m in page_matches[:20]:  # cap matches per page
            start, end = m.span()
            snippet_start = max(0, start - 60)
            snippet_end = min(len(text), end + 60)
            matches.append({
                "page": idx + 1,
                "char_start": start,
                "char_end": end,
                "snippet": text[snippet_start:snippet_end].replace("\n", " ").strip(),
            })
    return {
        "query": query,
        "case_sensitive": case_sensitive,
        "page_count": total_pages,
        "match_count": len(matches),
        "matches": matches,
    }


def _word_count(data: bytes) -> Dict[str, Any]:
    reader = _open_pypdf(data)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise HTTPException(status_code=400, detail="PDF is encrypted; cannot read")
    total = len(reader.pages)
    pages = min(total, MAX_PAGES_TEXT)
    word_total = 0
    char_total = 0
    per_page = []
    for idx in range(pages):
        try:
            text = reader.pages[idx].extract_text() or ""
        except Exception:
            text = ""
        words = len(text.split())
        chars = len(text)
        word_total += words
        char_total += chars
        per_page.append({"page": idx + 1, "words": words, "chars": chars})
    return {
        "page_count": total,
        "pages_analyzed": pages,
        "word_total": word_total,
        "char_total": char_total,
        "per_page": per_page,
    }


def _info(data: bytes) -> Dict[str, Any]:
    reader = _open_pypdf(data)
    has_text = False
    sample_pages = min(3, len(reader.pages))
    for idx in range(sample_pages):
        try:
            t = reader.pages[idx].extract_text() or ""
        except Exception:
            t = ""
        if t.strip():
            has_text = True
            break
    return {
        "size_bytes": len(data),
        "page_count": len(reader.pages),
        "encrypted": reader.is_encrypted,
        "has_extractable_text": has_text,
        "is_pdf": _is_pdf(data),
    }


# ---------------------------------------------------------------------------
# Generic source-handling endpoint helper
# ---------------------------------------------------------------------------
async def _resolve_from_request(
    file: Optional[UploadFile],
    url_form: Optional[str],
    body_url: Optional[str],
) -> bytes:
    """
    Accept any of: multipart `file`, multipart `url`, JSON `{"url": ...}`.
    """
    chosen_url = url_form or body_url
    data = await _resolve_pdf(file, chosen_url)
    if not _is_pdf(data):
        raise HTTPException(
            status_code=400,
            detail="File is not a valid PDF (missing %PDF magic bytes)",
        )
    return data


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def root():
    return {
        "api": "PDF Parser & Intelligence API",
        "version": "1.0.0",
        "docs": "/docs",
        "max_pdf_mb": MAX_PDF_BYTES // (1024 * 1024),
    }


# ---------------------------------------------------------------------------
# POST /info  — quick info
# ---------------------------------------------------------------------------
@app.post(
    "/info",
    summary="Quick PDF info",
    description="Lightweight check: file size, page count, encryption status, whether the PDF has extractable text.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def info_endpoint(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    body: Optional[UrlBody] = Body(None),
):
    body_url = str(body.url) if body and body.url else None
    data = await _resolve_from_request(file, url, body_url)
    result = await _run_sync(_info, data)
    return success(result)


# ---------------------------------------------------------------------------
# POST /metadata  — full metadata
# ---------------------------------------------------------------------------
@app.post(
    "/metadata",
    summary="Extract PDF metadata",
    description="Title, author, subject, keywords, creator, producer, creation/modification dates, and page count.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def metadata_endpoint(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    body: Optional[UrlBody] = Body(None),
):
    body_url = str(body.url) if body and body.url else None
    data = await _resolve_from_request(file, url, body_url)
    result = await _run_sync(_extract_metadata, data)
    return success(result)


# ---------------------------------------------------------------------------
# POST /extract-text  — full text extraction
# ---------------------------------------------------------------------------
@app.post(
    "/extract-text",
    summary="Extract all text from a PDF",
    description="Returns full text concatenated and per-page text. Capped at the first 500 pages.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def extract_text_endpoint(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    body: Optional[UrlBody] = Body(None),
):
    body_url = str(body.url) if body and body.url else None
    data = await _resolve_from_request(file, url, body_url)
    result = await _run_sync(_extract_text, data, 1, None)
    return success(result)


# ---------------------------------------------------------------------------
# POST /pages  — extract specific page range
# ---------------------------------------------------------------------------
@app.post(
    "/pages",
    summary="Extract text from specific pages",
    description="Extract text from a page range. Up to 500 pages per request.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def pages_endpoint(
    page_start: int = Query(1, ge=1, description="First page (1-indexed)"),
    page_end: Optional[int] = Query(None, ge=1, description="Last page inclusive"),
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    body: Optional[UrlBody] = Body(None),
):
    body_url = str(body.url) if body and body.url else None
    data = await _resolve_from_request(file, url, body_url)
    result = await _run_sync(_extract_text, data, page_start, page_end)
    return success(result)


# ---------------------------------------------------------------------------
# POST /tables  — extract tables
# ---------------------------------------------------------------------------
@app.post(
    "/tables",
    summary="Extract tables from a PDF",
    description=(
        "Detects tables on each page using pdfplumber and returns rows/columns "
        "for each. Useful for invoices, financial statements, and reports."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def tables_endpoint(
    page_start: int = Query(1, ge=1),
    page_end: Optional[int] = Query(None, ge=1),
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    body: Optional[UrlBody] = Body(None),
):
    body_url = str(body.url) if body and body.url else None
    data = await _resolve_from_request(file, url, body_url)
    result = await _run_sync(_extract_tables, data, page_start, page_end)
    return success(result)


# ---------------------------------------------------------------------------
# POST /search  — search for keyword/phrase
# ---------------------------------------------------------------------------
class SearchBody(BaseModel):
    url: Optional[AnyHttpUrl] = None
    query: str = Field(..., min_length=1, description="Keyword or phrase to search")
    case_sensitive: bool = False


@app.post(
    "/search",
    summary="Search for a keyword inside a PDF",
    description=(
        "Find every occurrence of a keyword/phrase across pages. "
        "Returns page numbers, character offsets, and surrounding text snippets."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def search_endpoint(
    query: Optional[str] = Query(None, description="Keyword/phrase to search"),
    case_sensitive: bool = Query(False),
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    body: Optional[SearchBody] = Body(None),
):
    # Resolve query from JSON body if not in querystring
    q = query or (body.query if body else None)
    if not q:
        raise HTTPException(status_code=400, detail="`query` is required")
    body_url = str(body.url) if body and body.url else None
    data = await _resolve_from_request(file, url, body_url)
    cs = case_sensitive or (body.case_sensitive if body else False)
    result = await _run_sync(_search_pdf, data, q, cs)
    return success(result)


# ---------------------------------------------------------------------------
# POST /word-count  — words/chars/page count
# ---------------------------------------------------------------------------
@app.post(
    "/word-count",
    summary="Word and character counts",
    description="Total words, characters, and per-page breakdown for the entire PDF.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def word_count_endpoint(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    body: Optional[UrlBody] = Body(None),
):
    body_url = str(body.url) if body and body.url else None
    data = await _resolve_from_request(file, url, body_url)
    result = await _run_sync(_word_count, data)
    return success(result)
