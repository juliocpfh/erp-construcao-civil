"""Gráficos Plotly (Gantt CPM, Curva S, indicadores)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

RED = "#C0392B"
BLUE = "#2E86C1"
GREEN = "#1E8449"
GRAY = "#95A5A6"
ORANGE = "#E67E22"


def gantt(sched: pd.DataFrame, show_baseline: bool = True, data_date: date | None = None,
          compact: bool = False) -> go.Figure:
    df = sched.copy()
    df["Início"] = pd.to_datetime(df["start"])
    df["Fim"] = pd.to_datetime(df["finish"]) + pd.Timedelta(days=1)
    df["Tarefa"] = df["code"] if compact else df["code"] + " · " + df["name"].map(lambda n: n if len(n) <= 26 else n[:25] + "…")
    df["Tipo"] = df.apply(
        lambda r: "Concluída" if r["progress"] >= 100 else ("Crítica" if r["critical"] else "Não crítica"), axis=1)
    df["Folga"] = df["slack"].astype(int)
    df["Avanço"] = df["progress"].round(1).astype(str) + "%"
    order = df.sort_values(["es", "code"])["Tarefa"].tolist()  # primeira tarefa no topo
    fig = px.timeline(
        df, x_start="Início", x_end="Fim", y="Tarefa", color="Tipo",
        color_discrete_map={"Crítica": RED, "Não crítica": BLUE, "Concluída": GRAY},
        hover_data={"name": True, "Folga": True, "Avanço": True, "predecessors": True, "delay": True, "Tipo": False},
        category_orders={"Tarefa": order, "Tipo": ["Crítica", "Não crítica", "Concluída"]},
    )
    # tarefas concluídas que estiveram no caminho crítico: contorno vermelho
    for trace in fig.data:
        trace.marker.line.width = 0
    if show_baseline:
        base = df.copy()
        base["Início"] = pd.to_datetime(base["baseline_start"])
        base["Fim"] = pd.to_datetime(base["baseline_finish"]) + pd.Timedelta(days=1)
        bfig = px.timeline(base, x_start="Início", x_end="Fim", y="Tarefa",
                           category_orders={"Tarefa": order})
        for tr in bfig.data:
            tr.name = "Baseline (planejado)"
            tr.showlegend = True
            tr.marker.color = "rgba(0,0,0,0)"
            tr.marker.line.color = "#7F8C8D"
            tr.marker.line.width = 1.5
            tr.width = 0.35
            tr.offset = 0.15
            fig.add_trace(tr)
    data_date = data_date or date.today()
    fig.add_vline(x=pd.Timestamp(data_date).value / 1e6, line_dash="dash", line_color=ORANGE)
    fig.add_annotation(x=pd.Timestamp(data_date), y=1.02, yref="paper", text="Hoje", showarrow=False,
                       font={"color": ORANGE})
    fig.update_yaxes(title=None)
    fig.update_layout(height=max(420, 22 * len(df) + 120), legend_title=None, margin={"l": 10, "r": 10, "t": 30, "b": 10},
                      legend={"orientation": "h", "y": -0.05}, barmode="overlay", xaxis_title=None)
    return fig


def s_curve(curve: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=curve["date"], y=curve["VP"], name="VP · Valor Planejado", line={"color": BLUE, "width": 3}))
    fig.add_trace(go.Scatter(x=curve["date"], y=curve["VA"], name="VA · Valor Agregado", line={"color": GREEN, "width": 3}))
    fig.add_trace(go.Scatter(x=curve["date"], y=curve["CR"], name="CR · Custo Real", line={"color": RED, "width": 3, "dash": "dot"}))
    fig.update_layout(height=380, yaxis_title="R$ acumulado", hovermode="x unified",
                      legend={"orientation": "h", "y": -0.18}, margin={"l": 10, "r": 10, "t": 30, "b": 10})
    fig.update_yaxes(tickprefix="R$ ", separatethousands=True)
    return fig


def index_gauge(value: float, title: str) -> go.Figure:
    color = GREEN if value >= 1 else (ORANGE if value >= 0.9 else RED)
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value, number={"valueformat": ".3f"}, title={"text": title},
        gauge={"axis": {"range": [0.5, 1.5]}, "bar": {"color": color},
               "steps": [{"range": [0.5, 0.9], "color": "#FADBD8"}, {"range": [0.9, 1.0], "color": "#FDEBD0"},
                         {"range": [1.0, 1.5], "color": "#D5F5E3"}],
               "threshold": {"line": {"color": "black", "width": 2}, "value": 1.0}},
    ))
    fig.update_layout(height=220, margin={"l": 20, "r": 20, "t": 50, "b": 10})
    return fig


def losses_bar(df: pd.DataFrame) -> go.Figure:
    top = df.sort_values("money_lost", ascending=False).head(12)
    fig = go.Figure()
    fig.add_trace(go.Bar(y=top["code"], x=(-top["cost_variance"]).clip(lower=0), name="Sobrecusto (CR > VA)",
                         orientation="h", marker_color=RED))
    fig.add_trace(go.Bar(y=top["code"], x=top["delay_cost"], name="Custo do atraso (indiretos)",
                         orientation="h", marker_color=ORANGE))
    fig.update_layout(barmode="stack", height=380, yaxis={"autorange": "reversed"}, xaxis_tickprefix="R$ ",
                      legend={"orientation": "h", "y": -0.15}, margin={"l": 10, "r": 10, "t": 30, "b": 10})
    return fig


def variance_scatter(df: pd.DataFrame) -> go.Figure:
    d = df[df["progress"] > 0].copy()
    d["Tipo"] = d["critical"].map({True: "Crítica", False: "Não crítica"})
    fig = px.scatter(d, x="finish_variance", y="cost_variance", color="Tipo", text="code",
                     color_discrete_map={"Crítica": RED, "Não crítica": BLUE},
                     labels={"finish_variance": "Desvio de término (dias)", "cost_variance": "VA - CR (R$)"})
    fig.add_hline(y=0, line_color="gray")
    fig.add_vline(x=0, line_color="gray")
    fig.update_traces(textposition="top center")
    fig.update_layout(height=380, margin={"l": 10, "r": 10, "t": 30, "b": 10})
    return fig


def weather_bar(rdo: pd.DataFrame) -> go.Figure:
    d = rdo.copy()
    d["mes"] = pd.to_datetime(d["date"]).dt.to_period("M").dt.to_timestamp()
    g = d.groupby(["mes", "weather"]).size().reset_index(name="dias")
    fig = px.bar(g, x="mes", y="dias", color="weather",
                 color_discrete_map={"Ensolarado": "#F4D03F", "Nublado": "#AAB7B8", "Chuva Fraca": "#5DADE2",
                                     "Chuva Forte": "#1A5276"}, labels={"mes": "", "weather": "Clima"})
    fig.update_layout(height=300, margin={"l": 10, "r": 10, "t": 30, "b": 10}, legend={"orientation": "h", "y": -0.2})
    return fig


def contact_timeline(events: list[dict]) -> go.Figure | None:
    rows = [e for e in events if e.get("date")]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["end"] = pd.to_datetime(df["end"]).fillna(df["date"] + timedelta(days=1))
    fig = px.timeline(df, x_start="date", x_end="end", y="type", color="type", hover_data={"description": True})
    fig.update_layout(height=260, showlegend=False, margin={"l": 10, "r": 10, "t": 20, "b": 10}, yaxis_title=None)
    return fig
