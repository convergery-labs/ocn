FROM python:3.12-slim AS base

WORKDIR /app

# tesseract-ocr + tesseract-ocr-jpn: OCR fallback for a small subset of
# IRBANK filing PDFs (irbank_financials source_type) that embed Type3 fonts
# with no ToUnicode CMap - pdfplumber/pdfminer/PyMuPDF all extract garbage
# (cid:N) glyph codes from these, confirmed live across ~2% of a
# 20-company/5-year sample (Towa 6315, Tokyo Ohka Kogyo 4186) - see
# pipeline.py's _ocr_extract_reason. This is the first apt-get/system
# dependency in this Dockerfile (everything else is pip-only) - only added
# because the affected filings recur across more than one filer, not a
# one-off worth ignoring.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-jpn \
    && rm -rf /var/lib/apt/lists/*

COPY news-retrieval/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/src/ /app/shared/
COPY news-retrieval/src/ /app/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/shared

CMD ["python", "__main__.py", "serve", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS dev

FROM base AS test
ENV PYTHONPATH=/app:/app/shared
COPY news-retrieval/requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt
COPY news-retrieval/tests/ tests/
COPY news-retrieval/pyproject.toml .
CMD ["pytest", "tests/", "-v"]
