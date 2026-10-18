import streamlit as st

import ui
from core import portfolio, store

st.set_page_config(page_title="Portfel XTB", layout="wide", page_icon=ui.ICON)
ui.apply_style()
st.markdown('<pre class="ascii">┌──[ PIXFUND ]──[ XTB PORTFOLIO ANALYZER ]──[ LOCAL ONLY ]──┐</pre>', unsafe_allow_html=True)
ui.header("start", "import → portfel → dywidendy_i_koszty → analiza (menu po lewej)")

data = store.load_all()
if data["reports"].empty:
    st.info("Brak danych – zacznij od strony **Import**.")
else:
    summ = portfolio.account_summary(data)
    st.metric("Wartość wg raportu XTB", f"{summ['razem'].sum():,.2f} zł")
    st.dataframe(summ, hide_index=True)
