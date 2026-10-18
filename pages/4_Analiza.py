import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import ui
from core import indicators as ind

st.set_page_config(page_title="Analiza", layout="wide", page_icon=ui.ICON)
ui.apply_style()
ui.header("analiza", "świece, średnie, wskaźniki, sygnały przecięć i Twoje transakcje")

data = ui.get_data(require=False)
tr = data["transactions"]
held = sorted(tr["ticker"].unique()) if len(tr) else []

with st.sidebar:
    names = dict(zip(tr["ticker"], tr["instrument"])) if len(tr) else {}
    pick = st.selectbox("Spółka z portfela", ["(wpisz własny)"] + held,
                        format_func=lambda t: f"{t} ({names[t]})" if names.get(t) and names[t] != t else t)
    ticker = (st.text_input("Ticker XTB", "PKN.PL").strip().upper() if pick == "(wpisz własny)" else pick)
    today = pd.Timestamp.today().normalize()
    rng = st.date_input("Zakres", (today - pd.DateOffset(years=1), today))
    st.markdown("**Wskaźniki**")
    use = {}
    for key, label, defaults in [("sma", "SMA", (15, 45)), ("ema", "EMA", (20,)), ("wma", "WMA", (20,))]:
        on = st.checkbox(label, value=(key == "sma"))
        txt = st.text_input(f"Okresy {label} (po przecinku)", ",".join(map(str, defaults)), disabled=not on)
        use[key] = [int(x) for x in txt.split(",") if x.strip().isdigit()] if on else []
    boll = st.checkbox("Bollinger (20, 2)")
    sr = st.checkbox("Wsparcia / opory")
    sr_win = st.number_input("Okno pivotów (świece)", 2, 30, 5, disabled=not sr)
    cross = st.checkbox("Przecięcia dwóch średnich (golden/death cross)", value=True)
    rsi_on = st.checkbox("RSI", value=True)
    rsi_n = st.number_input("RSI okres", 2, 100, 14, disabled=not rsi_on)
    macd_on = st.checkbox("MACD", value=True)
    macd_p = [st.number_input(n, 2, 200, v, key=f"macd{n}", disabled=not macd_on)
              for n, v in (("MACD szybka", 12), ("MACD wolna", 26), ("MACD sygnał", 9))]
    stoch_on = st.checkbox("Stochastic")
    atr_on = st.checkbox("ATR")
    obv_on = st.checkbox("OBV")
    show_tr = st.checkbox("Moje transakcje", value=True)

if len(rng) < 2:  # wybrano dopiero datę początkową
    st.stop()
start, end = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])
warm = pd.Timedelta(days=400)  # zapas na rozgrzanie wskaźników (SMA 200 itp.)
df = ui.fetch_ohlcv(ticker, start - warm, end)
if df.empty:
    st.error(f"Brak notowań dla {ticker} (Stooq i Yahoo). Sprawdź format tickera, np. PKN.PL, AAPL.US, EUNL.DE.")
    st.stop()

c = df["close"]
traces = []  # (nazwa, Series, kolor/styl)
for n in use["sma"]:
    traces.append((f"SMA {n}", ind.sma(c, n)))
for n in use["ema"]:
    traces.append((f"EMA {n}", ind.ema(c, n)))
for n in use["wma"]:
    traces.append((f"WMA {n}", ind.wma(c, n)))

panels = [p for p, on in [("RSI", rsi_on), ("MACD", macd_on), ("Stochastic", stoch_on), ("ATR", atr_on), ("OBV", obv_on)] if on]
rows = 2 + len(panels)
heights = [0.58, 0.1] + [0.32 / max(len(panels), 1)] * len(panels)
fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=heights)
v = df.loc[start:]
fig.add_candlestick(x=v.index, open=v["open"], high=v["high"], low=v["low"], close=v["close"], name=ticker,
                    increasing_line_color=ui.UP, decreasing_line_color=ui.DOWN,
                    increasing_fillcolor=ui.UP, decreasing_fillcolor=ui.DOWN, row=1, col=1)
ma_colors = [ui.COLORS[1], ui.COLORS[2], ui.COLORS[4], ui.COLORS[3]]  # cyan, amber, violet, magenta
for i, (name, s) in enumerate(traces):
    fig.add_scatter(x=v.index, y=s.loc[start:], name=name, mode="lines",
                    line=dict(width=1.5, color=ma_colors[i % len(ma_colors)]), row=1, col=1)
if boll:
    bb = ind.bollinger(c).loc[start:]
    for col, dash in (("upper", "dot"), ("mid", "dash"), ("lower", "dot")):
        fig.add_scatter(x=bb.index, y=bb[col], name=f"Bollinger {col}", line=dict(width=1, dash=dash, color=ui.MUTED),
                        row=1, col=1)
if sr:
    sup, res = ind.pivots(df["high"], df["low"], int(sr_win))
    for ser, name, color in ((sup.loc[start:], "wsparcie", ui.UP), (res.loc[start:], "opór", ui.DOWN)):
        for lvl in ser.tail(4):
            fig.add_hline(y=lvl, line=dict(color=color, width=1, dash="dash"), opacity=0.6, row=1, col=1)

if cross and len(traces) >= 2:
    (n1, f), (n2, s2) = traces[0], traces[1]
    sig = ind.cross_signals(f, s2).loc[start:]
    for val, nm, sym, col in ((1, f"Golden cross ({n1}/{n2})", "star", ui.COLORS[2]), (-1, f"Death cross ({n1}/{n2})", "x", ui.COLORS[3])):
        pts = sig[sig == val].index
        fig.add_scatter(x=pts, y=c.loc[pts], mode="markers", name=nm, marker=dict(symbol=sym, size=13, color=col,
                        line=dict(width=1, color=ui.SURFACE)), row=1, col=1)
elif cross:
    st.sidebar.caption("Przecięcia wymagają co najmniej dwóch średnich (np. SMA 15, 45).")

if show_tr and held:
    t = tr[(tr["ticker"] == ticker) & (tr["data"] >= start) & (tr["data"] < end + pd.Timedelta(days=1))]
    for typ, sym, col in (("kupno", "triangle-up", ui.COLORS[1]), ("sprzedaż", "triangle-down", ui.COLORS[3])):
        x = t[t["typ"] == typ]
        fig.add_scatter(x=x["data"], y=x["cena"], mode="markers", name=f"Moje: {typ}",
                        marker=dict(symbol=sym, size=11, color=col, line=dict(width=1.5, color=ui.SURFACE)),
                        text=x["ilość"].map(lambda q: f"{q:g} szt."), row=1, col=1)

fig.add_bar(x=v.index, y=v["volume"], name="Wolumen", marker_color="rgba(111,143,124,0.45)", showlegend=False, row=2, col=1)
r = 3
for p in panels:
    if p == "RSI":
        fig.add_scatter(x=v.index, y=ind.rsi(c, int(rsi_n)).loc[start:], name=f"RSI {int(rsi_n)}", showlegend=False,
                        line=dict(width=1.5, color=ui.COLORS[4]), row=r, col=1)
        fig.add_hline(y=70, line=dict(dash="dash", width=1, color=ui.MUTED), row=r, col=1)
        fig.add_hline(y=30, line=dict(dash="dash", width=1, color=ui.MUTED), row=r, col=1)
    elif p == "MACD":
        m = ind.macd(c, *map(int, macd_p)).loc[start:]
        fig.add_bar(x=m.index, y=m["hist"], name="MACD hist", marker_color="rgba(111,143,124,0.45)", showlegend=False, row=r, col=1)
        fig.add_scatter(x=m.index, y=m["macd"], name="MACD", showlegend=False, line=dict(width=1.5, color=ui.COLORS[1]), row=r, col=1)
        fig.add_scatter(x=m.index, y=m["signal"], name="Sygnał", showlegend=False, line=dict(width=1.5, color=ui.COLORS[2]), row=r, col=1)
    elif p == "Stochastic":
        st_ = ind.stochastic(df["high"], df["low"], c).loc[start:]
        fig.add_scatter(x=st_.index, y=st_["k"], name="%K", showlegend=False, row=r, col=1)
        fig.add_scatter(x=st_.index, y=st_["d"], name="%D", showlegend=False, row=r, col=1)
    elif p == "ATR":
        fig.add_scatter(x=v.index, y=ind.atr(df["high"], df["low"], c).loc[start:], name="ATR 14", showlegend=False, row=r, col=1)
    elif p == "OBV":
        fig.add_scatter(x=v.index, y=ind.obv(c, df["volume"]).loc[start:], name="OBV", showlegend=False, row=r, col=1)
    fig.update_yaxes(title_text=p, row=r, col=1)
    r += 1

ui.style_fig(fig, height=600 + 170 * len(panels))
fig.update_layout(xaxis_rangeslider_visible=False, legend=dict(y=1.02), dragmode="pan")
fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
fig.update_xaxes(rangeselector=dict(
    buttons=[dict(count=1, label="1M", step="month", stepmode="backward"),
             dict(count=3, label="3M", step="month", stepmode="backward"),
             dict(count=6, label="6M", step="month", stepmode="backward"),
             dict(count=1, label="YTD", step="year", stepmode="todate"),
             dict(count=1, label="1R", step="year", stepmode="backward"),
             dict(step="all", label="Całość")],
    bgcolor=ui.SURFACE, activecolor=ui.ACCENT, font=dict(color=ui.INK), x=1, xanchor="right", y=1.0, yanchor="bottom"),
    row=1, col=1)
ui.show(fig)
st.caption(f"{ticker}: {len(v)} sesji, ostatnie zamknięcie {c.iloc[-1]:,.2f} ({c.index[-1].date()}).")

with st.expander("Słownik pojęć i wskaźników – co znaczą i do czego służą"):
    st.markdown("""
**Wykres i elementy podstawowe**
- **Świeca japońska** – jedna sesja: otwarcie, maksimum, minimum, zamknięcie. Kolor pokazuje, czy cena wzrosła (zamknięcie > otwarcie), czy spadła. Długi cień = odrzucenie poziomu cenowego.
- **Wolumen** – liczba akcji/jednostek w sesji. Wzrost ceny przy dużym wolumenie jest wiarygodniejszy niż przy małym; potwierdza siłę trendu lub wybicia.
- **Moje transakcje** – Twoje kupna (▲) i sprzedaże (▼) naniesione na wykres; pozwalają ocenić, czy wchodziłeś/wychodziłeś w dobrych momentach.

**Średnie kroczące (nakładane na wykres ceny)** – wygładzają cenę i pokazują kierunek trendu. Cena powyżej średniej = trend wzrostowy, poniżej = spadkowy. Krótki okres (15–20) reaguje szybko, długi (50–200) pokazuje trend długoterminowy; średnie pełnią też rolę dynamicznych wsparć/oporów.
- **SMA** (prosta) – zwykła średnia z N ostatnich zamknięć; wszystkie dni mają równą wagę. Wolniejsza, mniej „nerwowa".
- **EMA** (wykładnicza) – nowsze notowania mają większą wagę, więc szybciej reaguje na zmiany. Podstawa MACD.
- **WMA** (ważona liniowo) – wagi malejące liniowo wstecz; reaguje szybciej niż SMA, ale łagodniej niż EMA.
- **Golden cross** (★) – krótsza średnia przecina dłuższą od dołu → sygnał możliwego początku trendu wzrostowego.
- **Death cross** (✕) – krótsza średnia przecina dłuższą od góry → sygnał możliwego trendu spadkowego. Sygnały spóźnione, w trendzie bocznym dają wiele fałszywych alarmów.

**Zmienność i poziomy**
- **Wstęgi Bollingera (20, 2)** – SMA 20 oraz pasma ±2 odchylenia standardowego. Zwężenie wstęg = niska zmienność (często przed gwałtownym ruchem); cena przy górnej wstędze = wysoko względem ostatnich sesji, przy dolnej = nisko. Nie jest to sam w sobie sygnał kupna/sprzedaży.
- **Wsparcia / opory** – poziomy, od których cena wcześniej się odbijała: wsparcie (zielone) to lokalne dołki, opór (czerwone) – lokalne szczyty. Złamanie oporu w górę (wybicie) lub wsparcia w dół to ważny sygnał; „okno pivotów" określa, ile świec z każdej strony musi być niższych/wyższych, by uznać punkt za szczyt/dołek.
- **ATR (Average True Range, 14)** – średni dzienny zakres ruchu ceny z uwzględnieniem luk. Mierzy zmienność, nie kierunek. Używany do ustalania stop-lossów (np. 2×ATR od ceny) i wielkości pozycji.

**Oscylatory (osobne panele pod wykresem)** – pokazują siłę/impet ruchu i stany wykupienia lub wyprzedania.
- **RSI (14)** – skala 0–100. Powyżej 70 = wykupienie (możliwa korekta w dół), poniżej 30 = wyprzedanie (możliwe odbicie). W silnym trendzie RSI może długo pozostawać w strefie ekstremalnej. Przydatne też do szukania dywergencji (cena robi nowy szczyt, RSI nie).
- **MACD (12, 26, 9)** – różnica EMA 12 i EMA 26 (linia MACD), do tego linia sygnału (EMA 9 z MACD) i histogram (różnica obu). Przecięcie MACD z sygnałem od dołu = sygnał kupna, od góry = sprzedaży; MACD powyżej zera = przewaga trendu wzrostowego. Rosnący histogram = narastający impet.
- **Stochastic (%K, %D)** – pozycja zamknięcia w zakresie high–low z ostatnich N sesji (0–100). %D to wygładzone %K. Powyżej 80 = wykupienie, poniżej 20 = wyprzedanie; przecięcie %K z %D sygnalizuje zwrot. Najlepiej sprawdza się w trendzie bocznym.
- **OBV (On-Balance Volume)** – skumulowany wolumen: dodawany w dni wzrostowe, odejmowany w spadkowe. Rosnące OBV przy rosnącej cenie potwierdza trend; rozbieżność (cena rośnie, OBV spada) ostrzega przed osłabieniem trendu.

*Żaden wskaźnik nie jest wyrocznią – to narzędzia pomocnicze. Najlepiej łączyć kilka z różnych grup (trend + impet + wolumen) i traktować jako potwierdzenie, nie samodzielny sygnał.*
""")
