"""Flash Report executivo em PDF gerado 100% em memória com ReportLab (sem disco, sem navegador)."""
from __future__ import annotations

import io
from datetime import date

import pandas as pd
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from erp.config import PROJECT_LOCATION, PROJECT_NAME
from erp.services.finance import brl

RED = colors.HexColor("#C0392B")
BLUE = colors.HexColor("#1F4E79")
GREEN = colors.HexColor("#1E8449")
ORANGE = colors.HexColor("#E67E22")


def _s_curve_drawing(curve: pd.DataFrame, width: float = 17 * cm, height: float = 6.5 * cm) -> Drawing:
    d = Drawing(width, height)
    lp = LinePlot()
    lp.x, lp.y = 1.6 * cm, 1.0 * cm
    lp.width, lp.height = width - 2.2 * cm, height - 1.8 * cm
    base = curve["date"].min()
    series = []
    for col, color in (("VP", BLUE), ("VA", GREEN), ("CR", RED)):
        pts = [((r.date - base).days, getattr(r, col) / 1e6) for r in curve.itertuples() if pd.notna(getattr(r, col))]
        series.append((pts or [(0, 0)], color))
    lp.data = [s for s, _ in series]
    for i, (_, color) in enumerate(series):
        lp.lines[i].strokeColor = color
        lp.lines[i].strokeWidth = 1.8
    lp.xValueAxis.labelTextFormat = lambda v: (base + pd.Timedelta(days=v)).strftime("%m/%y")
    lp.xValueAxis.labels.fontSize = 7
    lp.yValueAxis.labelTextFormat = "%.1f"
    lp.yValueAxis.labels.fontSize = 7
    d.add(lp)
    d.add(String(2, height - 10, "R$ milhões", fontSize=7))
    legend = Legend()
    legend.x, legend.y = width - 5.5 * cm, height - 0.2 * cm
    legend.fontSize = 7
    legend.columnMaximum = 1
    legend.colorNamePairs = [(BLUE, "VP (Planejado)"), (GREEN, "VA (Agregado)"), (RED, "CR (Real)")]
    d.add(legend)
    return d


def _table(data: list[list], col_widths: list[float], header_bg=BLUE, zebra: bool = True) -> Table:
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F2F4F7")))
    t.setStyle(TableStyle(style))
    return t


def build_flash_report(data: dict) -> bytes:
    """``data``: evm, summary, curve(DataFrame), critical(DataFrame), stock_alerts, embargo_alerts, losses."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.3 * cm, bottomMargin=1.3 * cm,
                            title=f"Flash Report - {PROJECT_NAME}", author="ERP Obras")
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=BLUE, fontSize=17, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=BLUE, fontSize=12, spaceBefore=8, spaceAfter=4)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    alert = ParagraphStyle("alert", parent=styles["Normal"], fontSize=9, textColor=RED)
    evm, summary = data["evm"], data["summary"]
    story = [
        Paragraph(f"Relatório Executivo (Flash Report) — {PROJECT_NAME}", h1),
        Paragraph(f"{PROJECT_LOCATION} · Data de status: {evm['data_date']:%d/%m/%Y} · Emitido por {data.get('user', '-')}", small),
        Spacer(1, 8),
    ]

    delay = summary.get("delay_days", 0)
    kpis = [
        ["Indicador", "Valor", "Indicador", "Valor"],
        ["Orçamento (BAC)", brl(evm["BAC"]), "IDC (CPI)", f"{evm['IDC']:.3f}"],
        ["Valor Planejado (VP)", brl(evm["VP"]), "IDP (SPI)", f"{evm['IDP']:.3f}"],
        ["Valor Agregado (VA)", brl(evm["VA"]), "Avanço físico", f"{evm['pct_earned']:.1f}% (plan. {evm['pct_planned']:.1f}%)"],
        ["Custo Real (CR)", brl(evm["CR"]), "Estimativa no término (EAC)", brl(evm["EAC"])],
        ["Término Baseline", f"{summary['baseline_finish']:%d/%m/%Y}", "Término Projetado", f"{summary['projected_finish']:%d/%m/%Y}"],
        ["Desvio de prazo", f"{delay:+d} dias", "Custo do atraso (indiretos)", brl(summary.get("delay_cost", 0))],
    ]
    t = _table(kpis, [4.2 * cm, 4.3 * cm, 4.6 * cm, 4.9 * cm])
    if evm["IDC"] < 1:
        t.setStyle(TableStyle([("TEXTCOLOR", (3, 1), (3, 1), RED)]))
    if evm["IDP"] < 1:
        t.setStyle(TableStyle([("TEXTCOLOR", (3, 2), (3, 2), RED)]))
    if delay > 0:
        t.setStyle(TableStyle([("TEXTCOLOR", (1, 6), (1, 6), RED), ("TEXTCOLOR", (3, 5), (3, 5), RED)]))
    story += [Paragraph("Indicadores PMI (Valor Agregado)", h2), t]

    curve = data.get("curve")
    if curve is not None and not curve.empty:
        story += [Paragraph("Curva S — VP x VA x CR", h2), _s_curve_drawing(curve)]

    alerts = []
    for a in data.get("embargo_alerts", []):
        alerts.append(Paragraph(f"<b>RISCO DE EMBARGO</b> — Araucária {a['tag']} em {a['date']}: {a['violations']}", alert))
    stock = data.get("stock_alerts")
    if stock is not None and not stock.empty:
        for r in stock.itertuples():
            alerts.append(Paragraph(
                f"<b>Estoque crítico</b> — {r.material}: saldo {r.stock:,.0f} {r.unit} &lt; necessidade "
                f"{r.required:,.0f} {r.unit} (lead time {r.lead_time_days} d; tarefas {r.tasks})", alert))
    story.append(Paragraph("Alertas", h2))
    story += alerts or [Paragraph("Nenhum alerta ativo.", styles["Normal"])]

    crit = data.get("critical")
    if crit is not None and not crit.empty:
        rows = [["Código", "Tarefa crítica", "Início", "Término", "Desvio", "%"]]
        for r in crit.head(14).itertuples():
            rows.append([r.code, Paragraph(r.name, ParagraphStyle("c", fontSize=7.5)), f"{r.start:%d/%m/%y}",
                         f"{r.finish:%d/%m/%y}", f"{int(r.finish_variance):+d} d", f"{r.progress:.0f}%"])
        story += [Paragraph("Caminho crítico (pendentes)", h2),
                  _table(rows, [1.6 * cm, 7.4 * cm, 2 * cm, 2 * cm, 1.8 * cm, 1.2 * cm], header_bg=RED)]

    losses = data.get("losses")
    if losses is not None and not losses.empty:
        rows = [["Tarefa", "Desvio prazo", "VA", "CR", "Perda estimada"]]
        for r in losses.head(8).itertuples():
            rows.append([Paragraph(f"{r.code} {r.name}", ParagraphStyle("c", fontSize=7.5)),
                         f"{int(r.finish_variance):+d} d", brl(r.earned_value), brl(r.actual_cost), brl(r.money_lost)])
        story += [Paragraph("Onde se perdeu tempo e dinheiro (Baseline x Real)", h2),
                  _table(rows, [7 * cm, 2.2 * cm, 2.6 * cm, 2.6 * cm, 2.6 * cm], header_bg=ORANGE)]

    story += [Spacer(1, 10), Paragraph(f"Gerado automaticamente pelo ERP Obras em {date.today():%d/%m/%Y}.", small)]
    doc.build(story)
    return buf.getvalue()


def build_placeholder_pdf(title: str, lines: list[str]) -> bytes:
    """PDF simples (usado na simulação de leis/laudos/projetos)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"])]
    story += [Paragraph(line, styles["Normal"]) for line in lines]
    doc.build(story)
    return buf.getvalue()
