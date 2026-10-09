"""Geração de mídias simuladas: fotos da obra, foto de NF (DANFE) e foto de produto."""
from __future__ import annotations

import io
import random
from datetime import date

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FLOORS = 10


def _font(size: int) -> ImageFont.ImageFont:
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def render_site_photo(day: date, foundation: float, structure: float, masonry: float, facade: float,
                      stage: str, weather: str = "Ensolarado", seed: int = 0,
                      size: tuple[int, int] = (640, 360)) -> bytes:
    """Desenha o edifício conforme o avanço: fundação (0-1), estrutura/alvenaria em pavimentos (0-11), fachada (0-1)."""
    rnd = random.Random(seed)
    w, h = size
    img = np.zeros((h, w, 3), dtype=np.uint8)
    rainy = "Chuva" in weather
    sky_top = np.array([150, 150, 150] if rainy else [235, 200, 140], dtype=np.float32)
    sky_bot = np.array([200, 200, 200] if rainy else [250, 235, 210], dtype=np.float32)
    for y in range(h):
        img[y, :] = (sky_top + (sky_bot - sky_top) * y / h).astype(np.uint8)
    ground = int(h * 0.82)
    cv2.rectangle(img, (0, ground), (w, h), (60, 90, 120), -1)  # terra

    # araucárias preservadas (cercadas)
    for ax in (40, w - 70):
        cv2.line(img, (ax, ground), (ax, ground - 120), (40, 60, 90), 5)
        for k in range(5):
            yy = ground - 120 + k * 9
            cv2.ellipse(img, (ax, yy), (34 - k * 3, 6), 0, 180, 360, (40, 110, 40), -1)
        cv2.rectangle(img, (ax - 30, ground - 18), (ax + 30, ground), (0, 140, 255), 1)

    bx0, bx1 = int(w * 0.33), int(w * 0.67)
    floor_h = int((ground - 40) / (FLOORS + 1.5))
    if foundation > 0:
        depth = int(18 * min(foundation, 1))
        cv2.rectangle(img, (bx0 - 10, ground), (bx1 + 10, ground + depth), (40, 60, 80), -1)
        for x in range(bx0, bx1 + 1, 18):
            if rnd.random() < foundation:
                cv2.line(img, (x, ground), (x, ground + depth + 10), (140, 140, 140), 3)

    full_structure = int(structure)
    for f in range(min(full_structure, FLOORS + 1)):
        y1 = ground - f * floor_h
        y0 = y1 - floor_h
        cv2.rectangle(img, (bx0, y0), (bx1, y1), (175, 175, 170), 2)
        for x in np.linspace(bx0, bx1, 6).astype(int):
            cv2.line(img, (x, y0), (x, y1), (160, 160, 155), 3)
        cv2.line(img, (bx0, y0), (bx1, y0), (130, 130, 130), 4)
        if f < masonry:
            cv2.rectangle(img, (bx0 + 3, y0 + 4), (bx1 - 3, y1 - 2), (70, 95, 185), -1)
            for x in np.linspace(bx0 + 12, bx1 - 30, 4).astype(int):
                cv2.rectangle(img, (x, y0 + 8), (x + 18, y0 + floor_h - 8), (90, 70, 50), -1)
        if facade > 0 and f < int((FLOORS + 1) * facade):
            cv2.rectangle(img, (bx0 + 3, y0 + 4), (bx1 - 3, y1 - 2), (200, 215, 225), -1)
            for x in np.linspace(bx0 + 12, bx1 - 30, 4).astype(int):
                cv2.rectangle(img, (x, y0 + 8), (x + 18, y0 + floor_h - 8), (150, 110, 60), -1)
    if 0 < structure - full_structure and full_structure <= FLOORS:  # pavimento em execução (formas/escoras)
        y1 = ground - full_structure * floor_h
        y0 = y1 - int(floor_h * (structure - full_structure))
        cv2.rectangle(img, (bx0, y0), (bx1, y1), (40, 140, 200), 1)
        for x in range(bx0, bx1, 10):
            cv2.line(img, (x, y0), (x, y1), (50, 160, 210), 1)

    if 0 < structure < FLOORS + 1:  # grua
        top = ground - int((max(structure, 1) + 2) * floor_h)
        cx = bx1 + 25
        cv2.line(img, (cx, ground), (cx, top), (0, 200, 255), 4)
        cv2.line(img, (cx - 150, top), (cx + 60, top), (0, 200, 255), 3)
        cv2.line(img, (cx - 120, top), (cx - 120, top + 50), (60, 60, 60), 1)

    if rainy:
        for _ in range(250 if weather == "Chuva Forte" else 90):
            x, y = rnd.randint(0, w), rnd.randint(0, h)
            cv2.line(img, (x, y), (x - 3, y + 12), (210, 210, 210), 1)

    cv2.rectangle(img, (0, 0), (w, 24), (30, 30, 30), -1)
    cv2.putText(img, f"{day:%d/%m/%Y} - {stage}"[:60], (8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (255, 255, 255), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes()


def render_invoice_image(number: str, supplier: str, cnpj: str, issue: date, total: float,
                         items: list[tuple[str, float, str, float]], iss: float = 0.0, inss: float = 0.0,
                         kind: str = "Material") -> bytes:
    """Imagem estilo DANFE/NFS-e (para testar o OCR)."""
    w, h = 1240, 1500
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    big, mid, small = _font(42), _font(30), _font(26)
    title = "NFS-e - NOTA FISCAL DE SERVIÇOS ELETRÔNICA" if kind != "Material" else "DANFE - DOCUMENTO AUXILIAR DA NF-e"
    d.rectangle((30, 30, w - 30, h - 30), outline="black", width=3)
    d.text((60, 60), title, font=mid, fill="black")
    d.text((60, 120), f"RAZÃO SOCIAL: {supplier}", font=mid, fill="black")
    d.text((60, 170), f"CNPJ: {cnpj}", font=mid, fill="black")
    d.text((60, 220), f"NF-e Nº {number}   SÉRIE 1", font=mid, fill="black")
    d.text((60, 270), f"DATA DE EMISSÃO: {issue:%d/%m/%Y}", font=mid, fill="black")
    d.line((60, 330, w - 60, 330), fill="black", width=2)
    d.text((60, 350), "DESCRIÇÃO                      QTD      UN      VL UNIT", font=small, fill="black")
    y = 400
    for desc, qty, unit, price in items[:12]:
        d.text((60, y), f"{desc[:28]:<28}  {qty:>9,.1f}  {unit:<5} {price:>10,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
               font=small, fill="black")
        y += 44
    y = max(y + 30, 1000)
    d.line((60, y, w - 60, y), fill="black", width=2)
    fmt = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
    if iss:
        d.text((60, y + 30), f"VALOR DO ISS: R$ {fmt(iss)}", font=mid, fill="black")
    if inss:
        d.text((60, y + 80), f"RETENÇÃO INSS: R$ {fmt(inss)}", font=mid, fill="black")
    d.text((60, y + 150), f"VALOR TOTAL DA NOTA: R$ {fmt(total)}", font=big, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_product_photo(name: str, seed: int = 0, size: tuple[int, int] = (480, 320)) -> bytes:
    rnd = random.Random(seed)
    w, h = size
    img = np.full((h, w, 3), 225, dtype=np.uint8)
    cv2.rectangle(img, (0, int(h * 0.7)), (w, h), (120, 130, 140), -1)
    color = (rnd.randint(40, 200), rnd.randint(40, 200), rnd.randint(40, 200))
    for i in range(rnd.randint(3, 6)):
        x = 40 + i * 70
        cv2.rectangle(img, (x, int(h * 0.35) - i % 2 * 20), (x + 60, int(h * 0.72)), color, -1)
        cv2.rectangle(img, (x, int(h * 0.35) - i % 2 * 20), (x + 60, int(h * 0.72)), (30, 30, 30), 1)
    cv2.putText(img, name[:34], (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 2, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes()
