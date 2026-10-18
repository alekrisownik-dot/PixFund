import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ui
from core import portfolio as pf

st.set_page_config(page_title="Portfel", layout="wide", page_icon=ui.ICON)
ui.apply_style()
ui.header("portfel", "wartość, zysk i stopy zwrotu wg raportu XTB lub cen rynkowych")

data = ui.get_data()
tr, co, op = data["transactions"], data["cash_ops"], data["open_positions"]
end = pd.Timestamp.today().normalize()
daily, close, fxs = ui.history(tr, co, end)

mode = st.radio("Wycena pozycji", ["Raport XTB", "Rynkowa (Yahoo + NBP)"], horizontal=True,
                help="Raport XTB: ceny i kursy walut z eksportu (zgodne z tym, co widzisz w XTB). "
                     "Rynkowa: zamknięcia giełdowe i kursy średnie NBP.")
xtb_mode = mode == "Raport XTB"
daily_mkt = daily  # TWR i benchmark zawsze z jednolitej wyceny rynkowej (bez skoku na ostatnim dniu)
if xtb_mode:  # ostatni dzień wyceniamy wg migawki raportu, reszta historii po cenach rynkowych
    daily = daily.copy()
    daily.loc[daily.index[-1], "pozycje"] = op["wartość"].sum()
    daily["wartość"] = daily["pozycje"] + daily["gotówka"]

# --- pozycje
names = dict(zip(tr["ticker"], tr["instrument"]))
prices_pln, missing = ui.current_prices_pln(tr, op, close, fxs)
if xtb_mode:
    prices_pln = {**prices_pln, **pf.snapshot_prices(op)}
    missing = []
if missing:
    st.warning(f"Brak notowań rynkowych dla {', '.join(missing)} – użyto ceny z raportu XTB.")
pos = pf.positions(tr, prices_pln, names)

pct = lambda x: "–" if pd.isna(x) else f"{x * 100:+,.2f}%"

# --- stan bieżący i wynik od początku (nie zależą od wybranego zakresu dat)
overall = pf.summary(daily, tr, co)
now = daily.iloc[-1]
o = st.columns(4)
o[0].metric("Aktualna wartość portfela", f"{overall['wartość']:,.2f} zł",
            help="Pozycje + wolna gotówka na kontach, stan na ostatni dzień.")
o[1].metric("Zysk overall", f"{overall['zysk']:+,.2f} zł", pct(overall["stopa_prosta"]),
            help="Wartość portfela minus wszystkie wpłaty netto, od początku historii. Procent względem wpłat netto.")
o[2].metric("Wpłacono netto", f"{overall['wpłaty_netto']:,.2f} zł")
o[3].metric("W tym pozycje / gotówka", f"{now['pozycje']:,.0f} / {now['gotówka']:,.0f} zł")

# --- skąd się bierze zysk overall: pozycje otwarte + zrealizowany + dywidendy/odsetki
bd = pf.profit_breakdown(tr, prices_pln)
fin = overall["dywidendy_netto"] + overall["odsetki_netto"]
z = st.columns(4)
z[0].metric("Zysk pozycji otwartych", f"{bd['niezrealizowany']:+,.2f} zł", pct(bd["niezrealizowany_proc"] / 100),
            help="Niezrealizowany: aktualna wartość pozycji minus ich koszt zakupu (odpowiednik 'Open position profit' w XTB).")
z[1].metric("Zysk zrealizowany", f"{bd['zrealizowany']:+,.2f} zł", help="Ze sprzedanych już akcji i ETF-ów.")
z[2].metric("Dywidendy + odsetki netto", f"{fin:+,.2f} zł", help="Po podatku u źródła i podatku od odsetek.")
z[3].metric("Razem = zysk overall", f"{bd['niezrealizowany'] + bd['zrealizowany'] + fin:+,.2f} zł")
st.caption("Zysk pozycji (niezrealizowany) + zrealizowany + dywidendy/odsetki = zysk overall. "
           "Procent przy pozycjach otwartych liczony względem ich kosztu zakupu.")

st.subheader("W wybranym zakresie")
start, stop = ui.date_range_picker(daily.index[0], daily.index[-1])
s = pf.summary(daily, tr, co, start, stop)
s["twr"] = pf.twr(daily_mkt, start, stop)

c = st.columns(5)
c[0].metric("Wartość na koniec zakresu", f"{s['wartość']:,.2f} zł")
c[1].metric("Zysk w zakresie", f"{s['zysk']:+,.2f} zł", pct(s["stopa_prosta"]))
c[2].metric("TWR", pct(s["twr"]), help="Liczony z wyceny rynkowej, niezależnie od trybu wyceny.")
c[3].metric("XIRR / rok", pct(s["xirr"]))
c[4].metric("Dywidendy netto", f"{s['dywidendy_netto']:,.2f} zł")
st.caption(("Wycena wg raportu XTB (jego ceny i kursy walut)." if xtb_mode else
            "Wycena po zamknięciach rynkowych (Yahoo) i kursach NBP; XTB wycenia po własnych cenach, więc kwoty "
            "mogą się różnić o ok. 1%.") +
           f" Wpłaty netto w zakresie: {s['wpłaty_netto']:,.2f} zł. "
           "XIRR dla krótkich okresów jest mocno zawyżony/zaniżony po annualizacji.")

# --- wartość vs wpłaty (+ zysk w zł)
sub = daily.loc[start:stop]
last = sub.iloc[-1]
fig = go.Figure()
fig.add_scatter(x=sub.index, y=sub["wpłaty_netto"], name="Wpłaty netto", line=dict(width=1.6, color=ui.COLORS[1], dash="dot"),
                hovertemplate="%{y:,.0f} zł")
fig.add_scatter(x=sub.index, y=sub["wartość"], name="Wartość portfela", line=dict(width=2, color=ui.COLORS[0]),
                fill="tonexty", fillcolor="rgba(0,177,85,.10)", hovertemplate="%{y:,.0f} zł")
hi = last["wartość"] >= last["wpłaty_netto"]  # etykiety rozsuwamy, gdy linie kończą się blisko siebie
for y, txt, col, dy in ((last["wartość"], f"{last['wartość']:,.0f} zł", ui.COLORS[0], 9 if hi else -9),
                        (last["wpłaty_netto"], f"{last['wpłaty_netto']:,.0f} zł", ui.COLORS[1], -9 if hi else 9)):
    fig.add_annotation(xref="paper", x=1, y=y, text=f"<span style='color:{col}'>●</span> {txt}", showarrow=False,
                       xanchor="left", xshift=6, yshift=dy, font=dict(color=ui.INK, size=12))
ui.style_fig(fig, "Wartość portfela vs wpłaty netto")
fig.update_layout(margin=dict(r=110))
fig.update_yaxes(tickformat=",.0f", ticksuffix=" zł")
ui.show(fig)

profit = sub["wartość"] - sub["wpłaty_netto"]
pf_fig = go.Figure()
pf_fig.add_scatter(x=sub.index, y=profit.clip(lower=0), name="Zysk", line=dict(width=1.5, color=ui.UP),
                   fill="tozeroy", fillcolor="rgba(0,177,85,.25)", hovertemplate="%{y:+,.0f} zł")
pf_fig.add_scatter(x=sub.index, y=profit.clip(upper=0), name="Strata", line=dict(width=1.5, color=ui.DOWN),
                   fill="tozeroy", fillcolor="rgba(227,85,85,.25)", hovertemplate="%{y:+,.0f} zł")
ui.style_fig(pf_fig, "Zysk / strata (wartość − wpłaty netto)", height=260)
pf_fig.update_yaxes(tickformat="+,.0f", ticksuffix=" zł")
ui.show(pf_fig)

st.subheader("Pozycje")
view = pos[["ticker", "nazwa", "rynek", "ilość", "śr_cena_zakupu", "koszt_pln", "wartość_pln",
            "zysk_pln", "zysk_proc", "udział"]].rename(columns={
    "śr_cena_zakupu": "śr. cena", "koszt_pln": "koszt zł", "wartość_pln": "wartość zł",
    "zysk_pln": "zysk zł", "zysk_proc": "zysk %", "udział": "udział %"})
sign_color = lambda v: ("" if pd.isna(v) or v == 0 else f"color: {ui.UP if v > 0 else ui.DOWN}; font-weight: 600")
styler = (view.style
          .format({"ilość": "{:.4f}", "śr. cena": "{:,.2f}", "koszt zł": "{:,.2f}", "wartość zł": "{:,.2f}",
                   "zysk zł": "{:+,.2f}", "zysk %": "{:+.2f}%", "udział %": "{:.1f}%"}, na_rep="–")
          .map(sign_color, subset=["zysk zł", "zysk %"]))
st.dataframe(styler, hide_index=True, height=min(80 + 35 * len(view), 520))

# --- struktura
st.subheader("Struktura")
left, right = st.columns([1, 2])
by = left.radio("Wg", ["Spółki", "Waluty", "Rynki"])
col = {"Spółki": "nazwa", "Waluty": "waluta", "Rynki": "rynek"}[by]
agg = pos.groupby(col, as_index=False)["wartość_pln"].sum().sort_values("wartość_pln", ascending=False)
top = agg.head(len(ui.COLORS))
rest = agg["wartość_pln"].iloc[len(ui.COLORS):].sum()  # powyżej 6 serii: reszta do 'Pozostałe' (szare)
labels = list(top[col]) + (["Pozostałe"] if rest > 0 else [])
values = list(top["wartość_pln"]) + ([rest] if rest > 0 else [])
colors = ui.COLORS[:len(top)] + ([ui.NEUTRAL] if rest > 0 else [])
pie = go.Figure(go.Pie(labels=labels, values=values, hole=0.62, sort=False, direction="clockwise",
                       marker=dict(colors=colors, line=dict(color=ui.SURFACE, width=2)),
                       textinfo="label+percent", textposition="outside", textfont=dict(color=ui.INK, size=12),
                       hovertemplate="%{label}<br>%{value:,.0f} zł (%{percent})<extra></extra>"))
pie.add_annotation(text=f"<b>{sum(values):,.0f} zł</b><br><span style='color:{ui.MUTED}'>w pozycjach</span>",
                   showarrow=False, font=dict(size=16, color="#e8fff1"))
ui.style_fig(pie)
pie.update_layout(showlegend=False, hovermode="closest", margin=dict(t=20, b=20, l=40, r=40), height=420)
with right:
    ui.show(pie)
if rest > 0:
    st.caption("Pełna lista spółek w tabeli powyżej; wykres pokazuje 6 największych, resztę łączy w „Pozostałe”.")

# --- benchmark
st.subheader("Porównanie z benchmarkiem")
name = st.radio("Benchmark", list(ui.BENCHMARKS), horizontal=True)
ticker, cur = ui.BENCHMARKS[name]
bench = ui.fetch_ohlcv(ticker, start - pd.Timedelta(days=10), stop)["close"]
if len(bench) < 5:
    st.warning(f"Za mało notowań dla {name} (Stooq i Yahoo) – nie da się narysować porównania.")
else:
    if cur != "PLN":  # benchmark w PLN, tak jak portfel
        rate = ui.fetch_fx(cur, start - pd.Timedelta(days=10), stop)
        bench = bench * rate.reindex(bench.index.union(rate.index)).ffill().reindex(bench.index)
    days = daily.loc[start:stop].index
    b = bench.reindex(bench.index.union(days)).ffill().reindex(days).dropna()
    port_idx = pf.twr_series(daily_mkt, start, stop).reindex(b.index)
    port_pct = (port_idx / port_idx.iloc[0] - 1) * 100  # zmiana od początku zakresu, w %
    bench_pct = (b / b.iloc[0] - 1) * 100
    cmp = go.Figure()
    cmp.add_scatter(x=port_pct.index, y=port_pct, name="Portfel (TWR)", line=dict(width=2, color=ui.COLORS[0]),
                    hovertemplate="%{y:+.2f}%")
    cmp.add_scatter(x=bench_pct.index, y=bench_pct, name=f"{name} (w PLN)", line=dict(width=2, color=ui.COLORS[1]),
                    hovertemplate="%{y:+.2f}%")
    cmp.add_hline(y=0, line=dict(color=ui.MUTED, width=1, dash="dash"))
    for y, txt, colr in ((port_pct.iloc[-1], f"Portfel {port_pct.iloc[-1]:+.1f}%", ui.COLORS[0]),
                         (bench_pct.iloc[-1], f"{name} {bench_pct.iloc[-1]:+.1f}%", ui.COLORS[1])):
        cmp.add_annotation(xref="paper", x=1, y=y, text=f"<span style='color:{colr}'>●</span> {txt}", showarrow=False,
                           xanchor="left", xshift=6, font=dict(color=ui.INK, size=12))
    ui.style_fig(cmp, f"Zmiana od początku zakresu: portfel vs {name}")
    cmp.update_layout(margin=dict(r=130))
    cmp.update_yaxes(ticksuffix="%", tickformat="+.0f")
    ui.show(cmp)
    d1, d2, d3 = st.columns(3)
    d1.metric("Portfel (TWR)", f"{port_pct.iloc[-1]:+.2f}%")
    d2.metric(name, f"{bench_pct.iloc[-1]:+.2f}%")
    d3.metric("Różnica", f"{port_pct.iloc[-1] - bench_pct.iloc[-1]:+.2f} p.p.",
              help="Punkty procentowe: stopa portfela minus stopa benchmarku.")
    note = " WIG20: Beta ETF WIG20TR (total return) jako zamiennik indeksu." if name == "WIG20" else ""
    st.caption("Portfel liczony stopą TWR (bez wpływu wpłat), benchmark przeliczony na PLN." + note)
