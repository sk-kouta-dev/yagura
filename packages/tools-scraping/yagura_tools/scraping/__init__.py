"""yagura-tools-scraping — web scraping, PDF extraction, OCR."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _httpx():
    try:
        import httpx  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-scraping requires 'httpx'") from exc
    return httpx


def _bs4():
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-scraping requires 'beautifulsoup4'") from exc
    return BeautifulSoup


# ---------------------------------------------------------------------------
# Web scraping
# ---------------------------------------------------------------------------


def _scrape_webpage(url: str, selector: str | None = None) -> ToolResult:
    httpx = _httpx()
    BeautifulSoup = _bs4()
    response = httpx.get(url, timeout=30, follow_redirects=True)
    soup = BeautifulSoup(response.text, "html.parser")
    if selector:
        element = soup.select_one(selector)
        text = element.get_text(strip=True) if element else ""
    else:
        text = soup.get_text(separator="\n", strip=True)
    return ToolResult(
        success=response.is_success,
        data={"url": url, "status": response.status_code, "text": text},
        reliability=ReliabilityLevel.REFERENCE,
    )


def _scrape_links(url: str, filter: str | None = None) -> ToolResult:
    httpx = _httpx()
    BeautifulSoup = _bs4()
    response = httpx.get(url, timeout=30, follow_redirects=True)
    soup = BeautifulSoup(response.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if filter and filter not in href:
            continue
        links.append({"href": href, "text": a.get_text(strip=True)})
    return ToolResult(success=response.is_success, data={"url": url, "links": links, "count": len(links)})


def _scrape_tables(url: str, index: int | None = None) -> ToolResult:
    httpx = _httpx()
    BeautifulSoup = _bs4()
    response = httpx.get(url, timeout=30, follow_redirects=True)
    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")
    if index is not None:
        tables = [tables[index]] if 0 <= index < len(tables) else []
    parsed = []
    for table in tables:
        rows = []
        for tr in table.find_all("tr"):
            rows.append([cell.get_text(strip=True) for cell in tr.find_all(["td", "th"])])
        parsed.append(rows)
    return ToolResult(success=True, data={"tables": parsed, "count": len(parsed)})


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _pdf_extract_text(file_path: str, pages: list[int] | None = None) -> ToolResult:
    try:
        import pypdf  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-scraping requires 'pypdf'") from exc
    reader = pypdf.PdfReader(file_path)
    targets = pages or list(range(len(reader.pages)))
    pages_text = []
    for i in targets:
        if 0 <= i < len(reader.pages):
            pages_text.append({"page": i, "text": reader.pages[i].extract_text() or ""})
    return ToolResult(
        success=True,
        data={"file_path": file_path, "pages": pages_text, "page_count": len(reader.pages)},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _pdf_split(file_path: str, output_dir: str, pages: list[int] | None = None) -> ToolResult:
    import pypdf  # type: ignore
    reader = pypdf.PdfReader(file_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    targets = pages or list(range(len(reader.pages)))
    written: list[str] = []
    for i in targets:
        if not (0 <= i < len(reader.pages)):
            continue
        writer = pypdf.PdfWriter()
        writer.add_page(reader.pages[i])
        dest = output / f"page_{i + 1}.pdf"
        with dest.open("wb") as f:
            writer.write(f)
        written.append(str(dest))
    return ToolResult(success=True, data={"written": written, "count": len(written)})


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------


def _ocr_image(file_path: str, language: str = "eng") -> ToolResult:
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise ImportError("OCR requires the [ocr] extra: pip install yagura-tools-scraping[ocr]") from exc
    text = pytesseract.image_to_string(Image.open(file_path), lang=language)
    return ToolResult(
        success=True,
        data={"file_path": file_path, "text": text},
        reliability=ReliabilityLevel.REFERENCE,  # OCR output is noisy — REFERENCE is safer.
    )


def _ocr_pdf(file_path: str, pages: list[int] | None = None, language: str = "eng") -> ToolResult:
    try:
        import pytesseract  # type: ignore
        from pdf2image import convert_from_path  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "OCR on PDFs requires [ocr] extra and `pdf2image` (+ poppler): pip install pdf2image"
        ) from exc
    images = convert_from_path(file_path)
    targets = pages or list(range(len(images)))
    pages_text = []
    for i in targets:
        if 0 <= i < len(images):
            pages_text.append({"page": i, "text": pytesseract.image_to_string(images[i], lang=language)})
    return ToolResult(
        success=True,
        data={"file_path": file_path, "pages": pages_text},
        reliability=ReliabilityLevel.REFERENCE,
    )


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def _T(name, description, props, required, handler, danger, **extra):
    return Tool(
        name=name, description=description,
        parameters={"type": "object", "properties": props, "required": required},
        handler=handler, danger_level=danger, tags=["scraping"], **extra,
    )


tools: list[Tool] = [
    _T("scrape_webpage", "Scrape a webpage and extract text.",
        {"url": {"type": "string"}, "selector": {"type": "string"}},
        ["url"], _scrape_webpage, DangerLevel.READ,
        default_reliability=ReliabilityLevel.REFERENCE),
    _T("scrape_links", "Extract all links from a page.",
        {"url": {"type": "string"}, "filter": {"type": "string"}},
        ["url"], _scrape_links, DangerLevel.READ,
        default_reliability=ReliabilityLevel.REFERENCE),
    _T("scrape_tables", "Extract tables from a page.",
        {"url": {"type": "string"}, "index": {"type": "integer"}},
        ["url"], _scrape_tables, DangerLevel.READ,
        default_reliability=ReliabilityLevel.REFERENCE),
    _T("pdf_extract_text", "Extract text from a PDF.",
        {"file_path": {"type": "string"}, "pages": {"type": "array", "items": {"type": "integer"}}},
        ["file_path"], _pdf_extract_text, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("pdf_split", "Split a PDF into individual pages.",
        {"file_path": {"type": "string"}, "output_dir": {"type": "string"}, "pages": {"type": "array", "items": {"type": "integer"}}},
        ["file_path", "output_dir"], _pdf_split, DangerLevel.MODIFY),
    _T("ocr_image", "Run OCR on an image file.",
        {"file_path": {"type": "string"}, "language": {"type": "string", "default": "eng"}},
        ["file_path"], _ocr_image, DangerLevel.READ,
        default_reliability=ReliabilityLevel.REFERENCE),
    _T("ocr_pdf", "Run OCR on a scanned PDF.",
        {"file_path": {"type": "string"}, "pages": {"type": "array", "items": {"type": "integer"}}, "language": {"type": "string", "default": "eng"}},
        ["file_path"], _ocr_pdf, DangerLevel.READ,
        default_reliability=ReliabilityLevel.REFERENCE),
]

__all__ = ["tools"]
