"""Gera o ícone do atalho (installer/erp_obras.ico) com Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

size = 256
img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([8, 8, size - 8, size - 8], radius=48, fill=(31, 78, 121, 255))
d.rectangle([60, 70, 196, 82], fill=(242, 169, 0, 255))      # lança do guindaste
d.rectangle([120, 70, 134, 200], fill=(242, 169, 0, 255))     # torre
d.rectangle([70, 150, 110, 200], fill=(255, 255, 255, 255))   # prédio
d.rectangle([146, 120, 190, 200], fill=(255, 255, 255, 255))
try:
    font = ImageFont.truetype("arialbd.ttf", 44)
except OSError:
    font = ImageFont.load_default()
d.text((size / 2, 228), "ERP", fill=(255, 255, 255, 255), font=font, anchor="ms")
out = Path(__file__).with_name("erp_obras.ico")
img.save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out)
