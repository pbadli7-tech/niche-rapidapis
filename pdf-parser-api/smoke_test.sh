#!/usr/bin/env bash
# Smoke test for PDF Parser API. Pass the Railway URL as the first arg.
# Example:
#   bash smoke_test.sh https://pdf-parser-production-xxxx.up.railway.app
set -e

BASE="${1:?Usage: $0 <railway-base-url>}"

# Use a small public PDF for testing.
TEST_PDF="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"

echo "=== Health check ==="
curl -sS -w "\nHTTP %{http_code}\n" "$BASE/" --max-time 15
echo ""

echo "=== /info via JSON URL body ==="
curl -sS -w "\nHTTP %{http_code}\n" -X POST "$BASE/info" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"$TEST_PDF\"}" --max-time 30
echo ""

echo "=== /metadata via JSON URL body ==="
curl -sS -w "\nHTTP %{http_code}\n" -X POST "$BASE/metadata" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"$TEST_PDF\"}" --max-time 30
echo ""

echo "=== /extract-text via JSON URL body ==="
curl -sS -w "\nHTTP %{http_code}\n" -X POST "$BASE/extract-text" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"$TEST_PDF\"}" --max-time 30 | head -c 600
echo ""

echo "=== /word-count ==="
curl -sS -w "\nHTTP %{http_code}\n" -X POST "$BASE/word-count" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"$TEST_PDF\"}" --max-time 30 | head -c 400
echo ""

echo "=== /search query=Dummy ==="
curl -sS -w "\nHTTP %{http_code}\n" -X POST "$BASE/search?query=Dummy" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"$TEST_PDF\"}" --max-time 30 | head -c 400
echo ""

echo "=== /tables ==="
curl -sS -w "\nHTTP %{http_code}\n" -X POST "$BASE/tables" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"$TEST_PDF\"}" --max-time 30 | head -c 400
echo ""

echo "=== Done. ==="
