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


def _find_money_after(labels: list[str], text: str) -> float | None:
    for label in labels:
        m = re.search(label + r"[^\d\n]{0,40}" + _MONEY, text, flags=re.IGNORECASE)
        if m:
            try:
                return parse_money(m.group(1))
            except ValueError:
                continue
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


def _parse_supplier(text: str) -> str | None:
    lines = [ln.strip(" :-|") for ln in text.splitlines() if ln.strip()]
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


def parse_invoice_text(text: str) -> dict:
    text = text or ""
    cnpj = re.search(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", text)
    number = re.search(r"(?:N[ºO°]\.?|N[UÚ]MERO|NF-?e?\s*N?[ºO°]?)\s*[:\-]?\s*(\d{3,9})", text, flags=re.IGNORECASE)
    total = _find_money_after(
        [r"VALOR\s+TOTAL\s+DA\s+NOTA", r"VALOR\s+TOTAL\s+DO\s+SERVI[CÇ]O", r"VALOR\s+TOTAL", r"TOTAL\s+A\s+PAGAR",
         r"VALOR\s+L[IÍ]QUIDO", r"TOTAL"], text)
    iss = _find_money_after([r"VALOR\s+DO\s+ISS", r"ISS(?:QN)?\s+RETIDO", r"\bISS(?:QN)?\b"], text)
    inss = _find_money_after([r"RETEN[CÇ][AÃ]O\s+(?:DE\s+)?INSS", r"VALOR\s+DO\s+INSS", r"\bINSS\b"], text)
    issued = _parse_date(text)
    return {
        "fornecedor": _parse_supplier(text),
        "cnpj": cnpj.group(0) if cnpj else None,
        "numero": number.group(1) if number else None,
        "valor": total,
        "emissao": issued,
        "iss": iss,
        "inss": inss,
    }


def read_invoice(image_bytes: bytes | None = None, text: str | None = None) -> dict:
    engine = "texto informado"
    if text is None and image_bytes is not None:
        text, engine = extract_text(image_bytes)
    fields = parse_invoice_text(text or "")
    found = sum(1 for k in ("fornecedor", "valor", "emissao") if fields.get(k))
    return {"text": text or "", "engine": engine, "fields": fields, "confidence": found / 3,
            "read_at": datetime.now().isoformat(timespec="seconds")}
