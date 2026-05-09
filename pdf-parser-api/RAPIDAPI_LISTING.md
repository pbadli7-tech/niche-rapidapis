# PDF Parser & Intelligence API — RapidAPI Listing Pack

Everything you need to fill in the RapidAPI Studio fields. Copy/paste-ready.

---

## General → Category
**Tools**

## General → Short Description (≤ 200 chars)

> Extract text, metadata, tables, and structured content from any PDF. Supports URL fetching and direct uploads. Built for RAG, document automation, search indexing, and data extraction.

## General → Long Description (Markdown)

```markdown
# PDF Parser & Intelligence API

The fastest way to add PDF parsing to your app. Extract text, metadata, tables, and structured content from any PDF — by URL or direct upload — with a single API call. Built for RAG pipelines, document automation, e-discovery, search indexing, and data-extraction workflows.

## What You Can Do

- **Extract Text** — Full text plus per-page text in one call. Handles complex layouts, multi-column documents, and embedded fonts.
- **Get Metadata** — Title, author, subject, keywords, creator, producer, creation/modification dates, and encryption status.
- **Extract Tables** — Detects tables on each page (rows × columns) using `pdfplumber`. Perfect for invoices, financial statements, and reports.
- **Search PDFs** — Find any keyword or phrase across hundreds of pages. Returns page numbers, character offsets, and surrounding snippets.
- **Page Range Extraction** — Pull text from specific page ranges instead of the whole document.
- **Word & Character Counts** — Total counts plus per-page breakdown.
- **Quick Info** — Lightweight check: file size, page count, encryption status, whether the PDF has extractable text (vs. scanned-image-only).

## Two Input Modes — Use Whichever Fits

- **By URL**: `POST` with JSON body `{"url": "https://example.com/file.pdf"}`
- **Direct Upload**: `POST` with multipart `file=@/path/to/file.pdf`

Every endpoint accepts both. No signed URLs, no S3 uploads, no juggling.

## Perfect For

- **RAG / AI document Q&A** — feed clean text into your LLM context
- **Invoice & receipt processing** — pull line items out of tables
- **Resume parsers** — extract structured candidate data
- **Compliance & e-discovery** — search across thousands of legal PDFs
- **Search engines** — index PDFs alongside HTML
- **Document automation** — auto-fill forms from existing PDFs
- **Research tools** — pull citations and figure captions from academic papers

## Why Developers Choose This API

- **Battle-tested stack** — `pypdf` for fast text + metadata, `pdfplumber` for table detection
- **No system dependencies on your end** — we handle Poppler/Tesseract; you make HTTP calls
- **Generous limits** — 25 MB max file, 500 pages for text/search, 100 pages for tables
- **Predictable pricing** — pay only for what you use beyond your tier
- **Generous free tier** — 100 requests/month, no credit card required
- **Sub-second responses** for typical 10–50-page PDFs
- **CORS-enabled** — call directly from web apps if you want
- **Clean JSON output** — consistent shape across all endpoints

## Use Cases We've Seen

- Auto-extract invoice line items into accounting software
- Build a "chat with this PDF" feature in days, not months
- Validate that uploaded resumes are real PDFs before processing
- Pre-index a library of contracts for full-text search
- Pull tabular data out of bank statements for personal-finance apps
- Generate summaries of research papers via LLM-on-extracted-text

## Limits

- **25 MB** max PDF size per request
- **500 pages** max for `/extract-text`, `/pages`, `/search`, `/word-count`
- **100 pages** max for `/tables` (table detection is heavier)

If you need higher limits, contact us — we can lift them on enterprise plans.

Stop wrestling with PDF libraries. Ship your document feature today.
```

---

## Definitions → Endpoints

All 7 endpoints are `POST` and require auth via the RapidAPI gateway. Inputs accept multipart upload or JSON body.

### 1. `POST /info`
**Quick PDF info**
- Description: Lightweight check — file size, page count, encryption status, whether the PDF has extractable text. Cheap; use for validation/triage before heavier extraction.
- Body: `multipart` (`file` or `url` field) **or** JSON `{"url": "..."}`
- Returns: `{size_bytes, page_count, encrypted, has_extractable_text, is_pdf}`

### 2. `POST /metadata`
**Extract PDF metadata**
- Description: Title, author, subject, keywords, creator, producer, creation/modification dates, page count, encryption status, plus full raw metadata dictionary.
- Body: same as `/info`
- Returns: `{page_count, encrypted, title, author, subject, keywords, creator, producer, creation_date, modification_date, raw}`

### 3. `POST /extract-text`
**Full text extraction**
- Description: Returns full concatenated text plus per-page text. Capped at the first 500 pages.
- Body: same as `/info`
- Returns: `{page_count, page_range, pages: [{page, text, char_count}], text, char_count, word_count}`

### 4. `POST /pages`
**Text from a specific page range**
- Description: Extract text from a specific page range. Up to 500 pages per request.
- Query: `page_start` (int, ≥1, default 1), `page_end` (int, ≥1, optional)
- Body: same as `/info`
- Returns: same shape as `/extract-text`

### 5. `POST /tables`
**Extract tables**
- Description: Detects tables on each page using `pdfplumber` and returns rows/columns for each table. Useful for invoices, financial statements, structured reports.
- Query: `page_start` (int, ≥1, default 1), `page_end` (int, ≥1, optional)
- Body: same as `/info`
- Returns: `{page_count, table_count, tables: [{page, table_index, row_count, col_count, rows: [[cell, cell, ...]]}]}`

### 6. `POST /search`
**Search a keyword across pages**
- Description: Find every occurrence of a keyword/phrase across pages. Returns page numbers, character offsets, and ~120-char surrounding snippets.
- Query: `query` (string, required), `case_sensitive` (bool, default false)
- Body: multipart (`file`/`url`) **or** JSON `{"url": "...", "query": "...", "case_sensitive": false}`
- Returns: `{query, case_sensitive, page_count, match_count, matches: [{page, char_start, char_end, snippet}]}`

### 7. `POST /word-count`
**Word and character counts**
- Description: Total words, characters, and per-page breakdown for the entire PDF.
- Body: same as `/info`
- Returns: `{page_count, pages_analyzed, word_total, char_total, per_page: [{page, words, chars}]}`

---

## Suggested 4-Tier Pricing (you fill this in)

Same shape as the other 10 APIs — adjust per the value of PDF parsing:

| Plan | Quota | Limit Type | Overage |
|------|-------|------------|---------|
| BASIC | 100 / month | Hard | — |
| PRO | 1,000 / month | Soft | $0.01 each |
| ULTRA | 5,000 / month | Soft | $0.007 each |
| MEGA | 25,000 / month | Soft | $0.005 each |

You said you'd handle the price part — these are just the values you used everywhere else, in case it's useful.

---

## Visibility
- Set to **Public**
- Confirm "I own or have rights to publish this API" checkbox

---

## Railway service setup (so the gateway has somewhere to point)

1. Railway → project → **Add → GitHub Repo** → select `pbadli7-tech/niche-rapidapis`
2. **Settings → Source → Add Root Directory**: leave empty (Dockerfile uses repo root)
3. **Settings → Source → Connect Environment to Branch**: `main`, then **Enable** auto-deploy
4. **Settings → Build → Builder**: Dockerfile
5. **Settings → Build → Dockerfile Path**: `pdf-parser-api/Dockerfile`
6. **Variables**:
   - `RAPIDAPI_PROXY_SECRET` (copy from one of the existing services)
   - `INTERNAL_API_KEY` (copy from one of the existing services)
   - `PORT=8011`
7. **Networking → Public Networking → Generate Domain** → note the URL
8. Wait for Online status → curl `<url>/` → should return `{"api":"PDF Parser & Intelligence API","version":"1.0.0",...}`

The same auto-deploy gotcha as before applies: if you ever push and nothing deploys, check Settings → Source → "Auto deploys when pushed to GitHub" is enabled (the icon should be solid, not crossed out).

---

## RapidAPI Studio setup (using that Railway URL as the gateway target)

1. RapidAPI → Studio → **+ Add API Project** → name "PDF Parser API"
2. **Definitions** → add 7 endpoints from the spec above; for each, set:
   - Method: `POST`
   - Path: `/info`, `/metadata`, etc.
   - Base URL (Gateway): the Railway URL from step 7 above
   - Headers passed: forward `X-RapidAPI-Proxy-Secret` (default)
3. **General** → paste short + long description from above; set Category = Tools
4. **Monetize → Public Plans** → set 4-tier pricing per your usual pattern (you said you'd do this)
5. **General → Visibility → API Project is Public** → check the rights box → toggle on → Save

That's it. Same flow you've done 11 times now.
