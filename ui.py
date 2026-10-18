"""Wspólne helpery stron Streamlit: ładowanie danych, filtr kont, notowania i kursy z cache_data."""
import random
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from core import fx, portfolio, prices, store

ASSETS = Path(__file__).parent / "assets"
LOGO, ICON = str(ASSETS / "logo.png"), str(ASSETS / "icon.png")
QUOTES = [  # (cytat, autor) – kultura hakerska / open source
    ("Talk is cheap. Show me the code.", "Linus Torvalds"),
    ("Information wants to be free.", "Stewart Brand"),
    ("Given enough eyeballs, all bugs are shallow.", "Eric S. Raymond"),
    ("The quieter you become, the more you are able to hear.", "Kali Linux"),
    ("Mistrust authority. Promote decentralization.", "Steven Levy, The Hacker Ethic"),
    ("Hackers build things, crackers break them.", "Eric S. Raymond"),
]

BENCHMARKS = {"WIG20": ("WIG20", "PLN"), "S&P 500": ("^SPX", "USD"), "Nasdaq 100": ("^NDX", "USD")}


def get_data(require: bool = True) -> dict:
    """Wczytuje dane z bazy i stosuje filtr kont z panelu bocznego."""
    data = store.load_all()
    if data["reports"].empty:
        if require:
            st.info("Brak danych – wgraj eksport XTB na stronie **Import**.")
            st.stop()
        return data
    label = dict(zip(data["reports"]["konto"],
                     data["cash_ops"].groupby("konto")["produkt"].first().reindex(data["reports"]["konto"]).fillna("")))
    options = list(data["reports"]["konto"])
    chosen = st.sidebar.multiselect("Konta", options, default=options,
                                    format_func=lambda k: f"{label.get(k, '')} ({k})")
    if not chosen:
        st.warning("Wybierz przynajmniej jedno konto.")
        st.stop()
    return {k: (v[v["konto"].isin(chosen)] if "konto" in v else v) for k, v in data.items()}


@st.cache_data(ttl=6 * 3600, show_spinner="Pobieram notowania…")
def fetch_ohlcv(ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return prices.get_prices(ticker, start, end)


@st.cache_data(ttl=6 * 3600, show_spinner="Pobieram kursy NBP…")
def fetch_fx(currency: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    try:
        return fx.daily_rates(fx.get_rates(currency, start, end), start, end)
    except requests.RequestException as e:
        st.error(f"Nie udało się pobrać kursów NBP ({currency}): {e}")
        st.stop()


def market_inputs(transactions: pd.DataFrame, end: pd.Timestamp):
    """(start, close: ticker->Series, fx: waluta->Series) dla wszystkich tickerów z transakcji."""
    start = transactions["data"].min().normalize()
    pstart = start - pd.Timedelta(days=7)
    close = {t: fetch_ohlcv(t, pstart, end)["close"] for t in transactions["ticker"].unique()}
    currencies = [c for c in transactions["waluta"].unique() if c not in ("PLN", "")]
    return start, close, {c: fetch_fx(c, pstart, end) for c in currencies}


@st.cache_data(show_spinner="Liczę wartość portfela…")
def history(transactions: pd.DataFrame, cash_ops: pd.DataFrame, end: pd.Timestamp):
    start, close, fxs = market_inputs(transactions, end)
    daily = portfolio.daily_values(transactions, cash_ops, close, fxs, start, end)
    return daily, close, fxs


def current_prices_pln(transactions, open_positions, close, fxs) -> tuple[dict, list]:
    """Cena jednostki w PLN: ostatnie notowanie × kurs NBP; brak notowań -> migawka raportu XTB.

    Zwraca (ceny, tickery_bez_notowań).
    """
    snap = portfolio.snapshot_prices(open_positions)
    cur = transactions.groupby("ticker")["waluta"].last()
    out, missing = {}, []
    for t, c in cur.items():
        s = close.get(t)
        if s is not None and len(s):
            out[t] = float(s.dropna().iloc[-1]) * (1.0 if c in ("PLN", "") else float(fxs[c].dropna().iloc[-1]))
        else:
            out[t] = snap.get(t, float("nan"))
            missing.append(t)
    return out, missing


def date_range_picker(first: pd.Timestamp, last: pd.Timestamp, key: str = "range"):
    """Presety + własny zakres. Zwraca (start, end) jako Timestamp."""
    preset = st.radio("Zakres", ["Całość", "YTD", "1 rok", "3 mies.", "Własny"], horizontal=True, key=f"{key}_p")
    if preset == "Własny":
        picked = st.date_input("Od – do", (first.date(), last.date()), min_value=first.date(),
                               max_value=last.date(), key=f"{key}_d")
        if len(picked) < 2:
            st.stop()  # wybrano dopiero datę początkową
        return pd.Timestamp(picked[0]), pd.Timestamp(picked[1])
    start = {"Całość": first, "YTD": pd.Timestamp(last.year, 1, 1), "1 rok": last - pd.DateOffset(years=1),
             "3 mies.": last - pd.DateOffset(months=3)}[preset]
    return max(start, first), last


# ------------------------------------------------------------------ wygląd (motyw "terminal")
SURFACE, GRID, INK, MUTED, ACCENT = "#0b0f0c", "#17251d", "#b7d9c4", "#6f8f7c", "#00ff9c"
# Paleta danych (kolejność stała) – zwalidowana skryptem dataviz na tle SURFACE (dark): pasmo L, chroma,
# CVD, kontrast. Jaskrawy neon (ACCENT) służy tylko elementom interfejsu, nie seriom danych.
COLORS = ["#00b155", "#25a0d0", "#c48600", "#e04080", "#957fee", "#e35555"]
UP, DOWN, NEUTRAL = COLORS[0], COLORS[5], "#5b6f62"
MONO = "'JetBrains Mono','Fira Code',ui-monospace,SFMono-Regular,Menlo,monospace"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;800&display=swap');
html, body, [class*="css"], [data-testid="stAppViewContainer"], .stMarkdown, button, input, label {{
  font-family: {MONO} !important; }}
[data-testid="stAppViewContainer"] {{
  background: radial-gradient(1200px 500px at 85% -10%, rgba(0,255,156,.07), transparent 60%), {SURFACE}; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{ background: #080b09; border-right: 1px solid {GRID}; }}
[data-testid="stSidebarHeader"] {{ height: auto; padding: 1.1rem 1rem .2rem; }}
[data-testid="stSidebarHeader"] div:has(> img[data-testid="stSidebarLogo"]) {{ height: auto !important; width: 100% !important; }}
img[data-testid="stSidebarLogo"] {{ height: 9rem !important; width: auto !important; max-width: 100%; object-fit: contain; object-position: left;
  filter: drop-shadow(0 0 10px rgba(0,255,156,.25)); }}
[data-testid="stSidebarNav"]::before {{ content: "{{QUOTE}}"; white-space: pre-wrap; display: block; color: {MUTED};
  font-size: .72rem; line-height: 1.45; font-style: italic; padding: .1rem 1rem .8rem; margin-bottom: .5rem;
  border-bottom: 1px dashed {GRID}; }}
[data-testid="stSidebarNav"] a {{ border-radius: 2px; }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{
  background: rgba(0,255,156,.08); border-left: 2px solid {ACCENT}; color: {ACCENT}; }}
h1.term {{ font-weight: 800; font-size: 1.9rem; letter-spacing: -.02em; color: {ACCENT};
  text-shadow: 0 0 12px rgba(0,255,156,.45); margin: .2rem 0 .1rem; padding: 0; }}
h1.term .ps {{ color: {MUTED}; font-weight: 400; text-shadow: none; font-size: 1rem; margin-right: .6rem; }}
h1.term .cur {{ animation: blink 1.1s steps(1) infinite; margin-left: 2px; }}
@keyframes blink {{ 50% {{ opacity: 0; }} }}
p.sub {{ color: {MUTED}; margin: 0 0 1rem; font-size: .85rem; }}
h2, h3 {{ color: {ACCENT} !important; font-weight: 600 !important; letter-spacing: -.01em; }}
h2::before, h3::before {{ content: "// "; color: {MUTED}; font-weight: 400; }}
[data-testid="stMetric"] {{ background: #0e1511; border: 1px solid {GRID}; border-left: 3px solid {ACCENT};
  border-radius: 2px; padding: .7rem .9rem; box-shadow: 0 0 18px rgba(0,255,156,.04) inset; }}
[data-testid="stMetricLabel"] {{ color: {MUTED}; text-transform: uppercase; letter-spacing: .08em; font-size: .72rem; }}
[data-testid="stMetricValue"] {{ font-weight: 800; color: #e8fff1; font-size: clamp(.9rem, 1.3vw, 1.45rem); }}
[data-testid="stMetricValue"] > div {{ overflow: visible !important; text-overflow: clip !important; white-space: nowrap; }}
[data-testid="stDataFrame"] {{ border: 1px solid {GRID}; border-radius: 2px; }}
div[data-baseweb="select"] > div, div[data-baseweb="input"] > div, [data-testid="stDateInput"] div[data-baseweb="input"] {{
  background: #0e1511; border: 1px solid {GRID}; border-radius: 2px; }}
span[data-baseweb="tag"] {{ background: rgba(0,255,156,.14) !important; color: {ACCENT} !important; border-radius: 2px; }}
.stButton > button, [data-testid="stBaseButton-primary"] {{ border-radius: 2px; border: 1px solid {ACCENT};
  background: transparent; color: {ACCENT}; text-transform: uppercase; letter-spacing: .06em; }}
.stButton > button:hover {{ background: rgba(0,255,156,.12); box-shadow: 0 0 14px rgba(0,255,156,.35); }}
[data-testid="stCaptionContainer"] {{ color: {MUTED}; }}
[data-testid="stAlert"] {{ border-radius: 2px; border: 1px solid {GRID}; }}
hr {{ border-color: {GRID}; }}
pre.ascii {{ color: {ACCENT}; text-shadow: 0 0 10px rgba(0,255,156,.4); font-size: .72rem; line-height: 1.05;
  background: transparent; border: none; padding: 0; margin: 0 0 .6rem; overflow: hidden; }}
.pos {{ color: {UP}; }} .neg {{ color: {DOWN}; }}
</style>
"""


def apply_style():
    """Motyw 'terminal': logo, cytat i CSS interfejsu (wywołaj na każdej stronie po set_page_config)."""
    if "quote" not in st.session_state:
        st.session_state["quote"] = random.choice(QUOTES)
    text, author = st.session_state["quote"]
    st.logo(LOGO, icon_image=ICON, size="large")
    st.markdown(_CSS.replace("{QUOTE}", f"“{text}”\\A— {author}"), unsafe_allow_html=True)


def header(title: str, subtitle: str = ""):
    st.markdown(f'<h1 class="term"><span class="ps">root@pixfund:~$</span>{title.lower()}'
                f'<span class="cur">▍</span></h1>' + (f'<p class="sub"># {subtitle}</p>' if subtitle else ""),
                unsafe_allow_html=True)


def style_fig(fig, title: str | None = None, height: int | None = None):
    """Wspólny wygląd wykresów: ciemne tło, cienka cicha siatka, mono, legenda nad wykresem, crosshair."""
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=MONO, color=INK, size=12), colorway=COLORS, height=height,
        margin=dict(l=8, r=8, t=72 if title else 40, b=8), hovermode="x unified",
        title=dict(text=title, x=0, font=dict(size=14, color=ACCENT)) if title else None,
        legend=dict(orientation="h", x=0, y=1.0, yanchor="bottom", bgcolor="rgba(0,0,0,0)", font=dict(color=INK)),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=ACCENT, font=dict(family=MONO, color="#e8fff1")))
    fig.update_xaxes(gridcolor=GRID, linecolor=GRID, zeroline=False, tickfont=dict(color=MUTED), showspikes=True,
                     spikecolor=MUTED, spikethickness=1, spikedash="dot", spikemode="across")
    fig.update_yaxes(gridcolor=GRID, linecolor=GRID, zerolinecolor=MUTED, tickfont=dict(color=MUTED))
    return fig


def show(fig, **kw):
    """Wykres bez nadpisywania naszego motywu przez Streamlit (theme=None)."""
    kw.setdefault("config", {"scrollZoom": True, "displayModeBar": True, "displaylogo": False, "doubleClick": "reset+autosize",
                             "modeBarButtonsToRemove": ["lasso2d", "select2d"]})
    st.plotly_chart(fig, width="stretch", theme=None, **kw)
