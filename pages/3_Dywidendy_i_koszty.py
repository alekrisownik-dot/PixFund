import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ui

st.set_page_config(page_title="Dywidendy i koszty", layout="wide", page_icon=ui.ICON)
ui.apply_style()
ui.header("dywidendy_i_koszty", "dywidendy, podatek u źródła, prowizje i odsetki")

data = ui.get_data()
tr, co = data["transactions"], data["cash_ops"]
freq = st.radio("Okres", ["Miesięcznie", "Rocznie"], horizontal=True)
rule = "M" if freq == "Miesięcznie" else "Y"
label = (lambda p: p.strftime("%Y-%m")) if rule == "M" else (lambda p: p.strftime("%Y"))


def by_period(df, col_date, col_val):
    return df.groupby(df[col_date].dt.to_period(rule))[col_val].sum().rename(index=str)


div = co[co["typ"] == "dywidenda"]
wht = co[co["typ"] == "podatek_u_źródła"]
intr = co[co["typ"].isin(["odsetki", "podatek_od_odsetek"])]

tab = pd.DataFrame({"dywidendy brutto": by_period(div, "data", "kwota"),
                    "podatek u źródła": by_period(wht, "data", "kwota")}).fillna(0)
tab["dywidendy netto"] = tab["dywidendy brutto"] + tab["podatek u źródła"]
c = st.columns(4)
c[0].metric("Dywidendy brutto", f"{div['kwota'].sum():,.2f} zł")
c[1].metric("Podatek u źródła", f"{wht['kwota'].sum():,.2f} zł")
c[2].metric("Dywidendy netto", f"{div['kwota'].sum() + wht['kwota'].sum():,.2f} zł")
c[3].metric("Prowizje", f"{tr['prowizja'].fillna(0).sum():,.2f} zł")

if tab.empty:
    st.info("Brak dywidend w wybranych kontach.")
else:
    fig = go.Figure()
    surface = dict(line=dict(color=ui.SURFACE, width=2))  # 2px odstęp między segmentami
    fig.add_bar(x=tab.index, y=tab["dywidendy brutto"], name="Brutto", marker=dict(color=ui.COLORS[0], **surface),
                hovertemplate="%{y:,.2f} zł")
    fig.add_bar(x=tab.index, y=tab["podatek u źródła"], name="Podatek u źródła",
                marker=dict(color=ui.COLORS[2], **surface), hovertemplate="%{y:,.2f} zł")
    fig.add_scatter(x=tab.index, y=tab["dywidendy netto"], name="Netto", mode="lines+markers",
                    line=dict(width=1.6, color=ui.COLORS[1]), marker=dict(size=8, color=ui.COLORS[1],
                    line=dict(color=ui.SURFACE, width=2)), hovertemplate="%{y:,.2f} zł")
    ui.style_fig(fig, f"Dywidendy – {freq.lower()}")
    fig.update_layout(barmode="relative")
    fig.update_xaxes(type="category")  # etykiety okresów, nie daty
    fig.update_yaxes(ticksuffix=" zł", tickformat=",.0f")
    ui.show(fig)
    st.dataframe(tab.round(2).reset_index(names="okres"), hide_index=True)

    st.subheader("Wg spółki")
    per = pd.DataFrame({"brutto": div.groupby("ticker")["kwota"].sum(),
                        "podatek": wht.groupby("ticker")["kwota"].sum()}).fillna(0)
    per["netto"] = per["brutto"] + per["podatek"]
    st.dataframe(per.sort_values("netto", ascending=False).round(2).reset_index(names="ticker"), hide_index=True)

st.subheader("Prowizje i odsetki")
comm = by_period(tr.assign(prowizja=tr["prowizja"].fillna(0)), "data", "prowizja")
cost = pd.DataFrame({"prowizje": comm, "odsetki netto": by_period(intr, "data", "kwota")}).fillna(0)
st.dataframe(cost.round(2).reset_index(names="okres"), hide_index=True)
if tr["prowizja"].fillna(0).sum() == 0:
    st.caption("W tych eksportach XTB nie naliczyło prowizji, więc koszt prowizji wynosi 0.")
