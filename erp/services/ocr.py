"""OCR de Notas Fiscais (Tesseract via pytesseract + pré-processamento OpenCV) com fallback.

Se o motor Tesseract não estiver disponível (ex.: falta do ``packages.txt``), o app continua
funcionando: o usuário cola o texto da NF (ou chave/QR) e o mesmo parser preenche os campos.
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path

import cv2
import numpy as np

_MONEY = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}|\d+\.\d{2})"


WINDOWS_DEFAULTS = [r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]


def tesseract_cmd() -> str | None:
    """Tesseract embutido no instalador (ERP_TESSERACT_CMD), no PATH ou na pasta padrão do Windows."""
    candidates = [os.environ.get("ERP_TESSERACT_CMD"), shutil.which("tesseract"), *WINDOWS_DEFAULTS]
    return next((c for c in candidates if c and Path(c).exists()), None)


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return tesseract_cmd() is not None


def preprocess(image_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Imagem inválida ou formato não suportado.")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    if w < 1400:  # amplia fotos pequenas de celular para melhorar o OCR
        scale = 1400 / w
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.fastNlMeansDenoising(gray, h=10)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)


def extract_text(image_bytes: bytes) -> tuple[str, str]:
    """Retorna (texto, motor). Motor 'indisponível' quando não há OCR instalado."""
    if not ocr_available():
        return "", "indisponível"
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd()
    img = preprocess(image_bytes)
    langs = pytesseract.get_languages(config="") if hasattr(pytesseract, "get_languages") else []
    lang = "por" if "por" in langs else "eng"
    text = pytesseract.image_to_string(img, lang=lang, config="--psm 6")
    return text, f"tesseract ({lang})"


def parse_money(raw: str) -> float:
    raw = raw.strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    return float(raw)


def _money_below(label: str, text: str) -> float | None:
    """DANFE: rótulos numa linha e valores na linha de baixo, na mesma ordem das colunas."""
    lines = text.splitlines()
    for i, line in enumerate(lines[:-1]):
        m = re.search(label, line, flags=re.IGNORECASE)
        if not m or re.search(r"\d", line[m.end():]):
            continue
        values = re.findall(_MONEY, lines[i + 1])
        if not values:
            continue
        col = min(int((m.start() + m.end()) / 2 / max(len(line), 1) * len(values)), len(values) - 1)
        try:
            return parse_money(values[col] if len(values) > 1 else values[0])
        except ValueError:
            continue
    return None


def _find_money_after(labels: list[str], text: str) -> float | None:
    for label in labels:
        m = re.search(label + r"[^\d\n]{0,40}" + _MONEY, text, flags=re.IGNORECASE)
        if m:
            try:
                return parse_money(m.group(1))
            except ValueError:
                pass
        below = _money_below(label, text)
        if below is not None:
            return below
    return None


def _parse_date(text: str) -> date | None:
    for label in (r"EMISS[AÃ]O", r"DATA\s+DE\s+EMISS", r"EMITIDA\s+EM", r"DATA"):
        m = re.search(label + r"[^\d\n]{0,30}(\d{2})[/.-](\d{2})[/.-](\d{4})", text, flags=re.IGNORECASE)
        if m:
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                continue
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


_COMPANY_SUFFIX = r"\b(LTDA|L\s?T\s?D\s?A|S\.?\s?A\.?|EIRELI|ME|EPP|MEI|COM[EÉ]RCIO|IND[UÚ]STRIA)\b"


def _parse_supplier(text: str, emitter: str | None = None) -> str | None:
    # canhoto da DANFE: "RECEBEMOS DE <EMITENTE> OS PRODUTOS..." / "RECEBI(EMOS) DE <EMITENTE>, OS PRODUTOS..."
    m = re.search(r"RECEB\w*\s*(?:\(EMOS\))?\s+DE\s+(.+?)(?:,|\s+OS\s+PRODUTOS|\s+A\s+IMPORT|\n)", text,
                  flags=re.IGNORECASE)
    if m and len(m.group(1).strip()) >= 3:
        return re.sub(r"\bL[I1l]DA\b", "LTDA", m.group(1).strip())  # OCR costuma ler LTDA como LIDA
    lines = [ln.strip(" :-|") for ln in (emitter or text).splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        m = re.match(r"(?:RAZ[AÃ]O\s+SOCIAL|EMITENTE|NOME/RAZ[AÃ]O SOCIAL|FORNECEDOR|PRESTADOR(?: DE SERVI[CÇ]OS)?)\s*[:\-]?\s*(.*)",
                     ln, flags=re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            if len(name) >= 3:
                return name
            if i + 1 < len(lines):
                return lines[i + 1]
    for ln in lines[:12]:
        if re.search(_COMPANY_SUFFIX, ln, flags=re.IGNORECASE) and len(ln) > 5:
            return ln
    return None


def _parse_cnpj(text: str, emitter: str) -> str | None:
    """CNPJ do emitente: o primeiro formatado antes do bloco do destinatário."""
    for part in (emitter, text):
        m = re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", part)
        if m:
            return m.group(0)
    m = re.search(r"CNPJ[^\d\n]{0,15}(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})", text, flags=re.IGNORECASE)
    return m.group(1) if m else None


def parse_invoice_text(text: str) -> dict:
    text = text or ""
    dest = re.search(r"DESTINAT[AÁ]RIO", text, flags=re.IGNORECASE)
    emitter = text[:dest.start()] if dest and dest.start() > 0 else text  # cabeçalho da DANFE = dados do emitente
    danfe_number = re.search(r"(?<![\d.,])(\d{3}\.\d{3}\.\d{3})(?![\d,-])", text)  # nº da DANFE: 000.310.631
    # "Nº 000.004.521" (DANFE), "NF-e N. 4521", "Número: 123"
    number = re.search(r"(?:N[ºO°]\.?|N[UÚ]MERO|NF-?e?\s*N?[ºO°.]*)\s*[:\-]?\s*(\d{1,3}(?:\.\d{3})+|\d{3,9})", text,
                       flags=re.IGNORECASE)
    total = _find_money_after(
        [r"VALOR\s+TOTAL\s+DA\s+NOTA", r"VALOR\s+TOTAL\s+DO\s+SERVI[CÇ]O", r"VALOR\s+TOTAL", r"TOTAL\s+A\s+PAGAR",
         r"VALOR\s+L[IÍ]QUIDO", r"TOTAL"], text)
    iss = _find_money_after([r"VALOR\s+DO\s+ISS", r"ISS(?:QN)?\s+RETIDO", r"\bISS(?:QN)?\b"], text)
    inss = _find_money_after([r"RETEN[CÇ][AÃ]O\s+(?:DE\s+)?INSS", r"VALOR\s+DO\s+INSS", r"\bINSS\b"], text)
    issued = _parse_date(text)
    return {
        "fornecedor": _parse_supplier(text, emitter),
        "cnpj": _parse_cnpj(text, emitter),
        "numero": str(int(danfe_number.group(1).replace(".", ""))) if danfe_number
        else (number.group(1).replace(".", "") if number else None),
        "valor": total,
        "emissao": issued,
        "iss": iss,
        "inss": inss,
    }


def is_pdf(data: bytes | None) -> bool:
    return bool(data) and data[:5] == b"%PDF-"


def pdf_page_images(pdf_bytes: bytes, max_pages: int = 3, scale: float = 2.5) -> list[bytes]:
    """Páginas do PDF como PNG (para OCR de PDF escaneado e para mostrar a nota na tela)."""
    import io

    import pypdfium2 as pdfium

    pages = []
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        for i in range(min(len(doc), max_pages)):
            buf = io.BytesIO()
            doc[i].render(scale=scale).to_pil().save(buf, format="PNG")
            pages.append(buf.getvalue())
    finally:
        doc.close()
    return pages


def pdf_layout_text(pdf_bytes: bytes) -> str:
    """Texto do PDF preservando a disposição das colunas (linhas da tabela de itens inteiras)."""
    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((page.extract_text(extraction_mode="layout") or "") for page in reader.pages[:5])
    except Exception:  # noqa: BLE001
        return ""


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, str]:
    """Texto da NF em PDF: lido direto do arquivo (DANFE gerado por sistema) ou por OCR das páginas (escaneado)."""
    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:5])
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"PDF inválido ou protegido: {exc}") from exc
    if len(re.sub(r"\s", "", text)) >= 40:
        return text, "texto do PDF"
    if not ocr_available():
        return text, "PDF escaneado (OCR indisponível)"
    parts, engine = [], "indisponível"
    for img in pdf_page_images(pdf_bytes):
        t, engine = extract_text(img)
        parts.append(t)
    return "\n".join(parts), f"PDF escaneado · {engine}"


def read_invoice(image_bytes: bytes | None = None, text: str | None = None) -> dict:
    """Lê a NF a partir de foto, PDF (texto ou escaneado) ou texto colado."""
    engine = "texto informado"
    if text is None and is_pdf(image_bytes):
        text, engine = extract_pdf_text(image_bytes)
    elif text is None and image_bytes is not None:
        text, engine = extract_text(image_bytes)
    from erp.services.nf_import import parse_items_text

    fields = parse_invoice_text(text or "")
    items = parse_items_text(text or "")
    if is_pdf(image_bytes) and engine == "texto do PDF":
        # tabela de itens: a leitura "em colunas" do PDF às vezes separa cada célula; usa a que achar mais itens
        layout = parse_items_text(pdf_layout_text(image_bytes))
        if len(layout) > len(items):
            items = layout
    found = sum(1 for k in ("fornecedor", "valor", "emissao") if fields.get(k))
    return {"text": text or "", "engine": engine, "fields": fields, "confidence": found / 3,
            "items": [i.as_dict() for i in items],
            "read_at": datetime.now().isoformat(timespec="seconds")}
