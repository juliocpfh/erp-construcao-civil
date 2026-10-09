"""DANFE de teste no layout real (células desenhadas por coluna, descrição quebrada em 2 linhas,
colunas de ICMS/IPI depois do valor total), como os PDFs que os sistemas emissores geram."""
from __future__ import annotations

import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ITEMS = [
    # código, descrição (linhas), NCM, CST, CFOP, UN, qtd, v.unit, v.total
    ("7891234", ["CIMENTO PORTLAND CP II-F-32 SACO", "50KG VOTORANTIM"], "25232910", "000", "5102", "SC",
     "120,0000", "38,5000", "4.620,00"),
    ("ARG-AC3", ["ARGAMASSA COLANTE AC-III CINZA 20KG"], "32149000", "000", "5102", "SC", "80,0000", "34,9000",
     "2.792,00"),
    ("BL1419", ["BLOCO CERAMICO VEDACAO 14X19X39", "6 FUROS"], "69041000", "060", "5405", "UN", "6.000,0000",
     "3,1300", "18.780,00"),
    ("VERG10", ["VERGALHAO CA-50 10MM BARRA 12M"], "72142000", "000", "5102", "BR", "150,0000", "62,4500",
     "9.367,50"),
]
TOTAL = "35.559,50"
COLS = [20, 70, 230, 275, 300, 330, 352, 400, 445, 495, 530, 560]  # x de cada coluna


def danfe_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 6)
    y = 810
    for label, value in [("RECEBEMOS DE DEPOSITO CURITIBANO DE MATERIAIS LTDA OS PRODUTOS CONSTANTES DA NOTA FISCAL", ""),
                         ("DANFE", "Nº 000.004.521  SÉRIE 001"),
                         ("DEPOSITO CURITIBANO DE MATERIAIS LTDA", "CNPJ 12.345.678/0001-95"),
                         ("NATUREZA DA OPERAÇÃO", "VENDA DE MERCADORIA"),
                         ("DESTINATÁRIO / REMETENTE", "CONSTRUTORA EXEMPLO LTDA  CNPJ 98.765.432/0001-10"),
                         ("DATA DA EMISSÃO", "28/09/2026")]:
        c.drawString(20, y, label)
        c.drawString(330, y, value)
        y -= 14
    c.drawString(20, y, "CÁLCULO DO IMPOSTO")
    y -= 10
    for x, t in zip([20, 120, 220, 320, 420, 500], ["BASE DE CÁLC. DO ICMS", "VALOR DO ICMS", "VALOR DO FRETE",
                                                    "VALOR TOTAL DOS PRODUTOS", "DESCONTO", "VALOR TOTAL DA NOTA"]):
        c.drawString(x, y, t)
    y -= 8
    for x, t in zip([20, 120, 220, 320, 420, 500], ["35.559,50", "4.267,14", "0,00", TOTAL, "0,00", TOTAL]):
        c.drawString(x, y, t)
    y -= 18
    c.drawString(20, y, "DADOS DOS PRODUTOS / SERVIÇOS")
    y -= 10
    head = ["CÓDIGO", "DESCRIÇÃO DO PRODUTO / SERVIÇO", "NCM/SH", "O/CST", "CFOP", "UN", "QUANT.", "VALOR UNIT.",
            "VALOR TOTAL", "B.CÁLC ICMS", "VALOR ICMS", "ALÍQ. ICMS"]
    for x, t in zip(COLS, head):
        c.drawString(x, y, t)
    y -= 10
    for code, desc, ncm, cst, cfop, un, qty, vu, vt in ITEMS:
        icms = f"{float(vt.replace('.', '').replace(',', '.')) * 0.12:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        row = [code, desc[0], ncm, cst, cfop, un, qty, vu, vt, vt, icms, "12,00"]
        for x, t in zip(COLS, row):
            c.drawString(x, y, t)
        for extra in desc[1:]:
            y -= 7
            c.drawString(COLS[1], y, extra)
        y -= 10
    y -= 10
    c.drawString(20, y, "DADOS ADICIONAIS")
    c.drawString(20, y - 8, "INFORMAÇÕES COMPLEMENTARES: PEDIDO 778 - ENTREGA NA OBRA")
    c.save()
    return buf.getvalue()


EXPECTED = [("CIMENTO PORTLAND CP II-F-32 SACO 50KG VOTORANTIM", 120.0, "sc", 38.5, 4620.0, "7891234"),
            ("ARGAMASSA COLANTE AC-III CINZA 20KG", 80.0, "sc", 34.9, 2792.0, "ARG-AC3"),
            ("BLOCO CERAMICO VEDACAO 14X19X39 6 FUROS", 6000.0, "un", 3.13, 18780.0, "BL1419"),
            ("VERGALHAO CA-50 10MM BARRA 12M", 150.0, "br", 62.45, 9367.5, "VERG10")]
