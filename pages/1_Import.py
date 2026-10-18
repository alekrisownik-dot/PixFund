import pandas as pd
import streamlit as st

import ui
from core import store

st.set_page_config(page_title="Import", layout="wide", page_icon=ui.ICON)
ui.apply_style()
ui.header("import", "wgraj pliki .xlsx (IKE i/lub rachunek zwykły); powtórne wgranie niczego nie dubluje")

files = st.file_uploader("Pliki XTB (.xlsx)", type="xlsx", accept_multiple_files=True)
if files and st.button("Importuj", type="primary"):
    rows = []
    for f in files:
        try:
            r = store.import_file(f)
        except Exception as e:  # zły format pliku
            st.error(f"{f.name}: nie udało się wczytać ({e})")
            continue
        rows.append({"plik": f.name, "konto": r["konto"], "nowe transakcje": r["nowe_transakcje"],
                     "nowe operacje gotówkowe": r["nowe_operacje_gotówkowe"], "duplikaty": r["duplikaty"],
                     "pozycje zaktualizowane": r["pozycje_zaktualizowane"]})
        for w in r["ostrzeżenia"]:
            st.warning(f"{f.name}: {w}")
    if rows:
        st.success("Import zakończony.")
        st.dataframe(pd.DataFrame(rows), hide_index=True)

data = store.load_all()
if data["reports"].empty:
    st.info("Baza jest pusta.")
    st.stop()

st.subheader("Zawartość bazy")
tr, co = data["transactions"], data["cash_ops"]
rows = []
for _, rep in data["reports"].iterrows():
    k = rep["konto"]
    t, c = tr[tr["konto"] == k], co[co["konto"] == k]
    dates = pd.concat([t["data"], c["data"]])
    rows.append({"konto": k, "produkt": c["produkt"].iloc[0] if len(c) else "",
                 "od": dates.min().date(), "do": dates.max().date(),
                 "transakcje": len(t), "operacje gotówkowe": len(c), "stan raportu (UTC)": rep["data_raportu"]})
st.dataframe(pd.DataFrame(rows), hide_index=True)

c1, c2 = st.columns(2)
c1.markdown("**Transakcje wg typu**")
c1.dataframe(tr.groupby(["konto", "typ"]).size().rename("liczba").reset_index(), hide_index=True)
c2.markdown("**Operacje gotówkowe wg typu**")
c2.dataframe(co.groupby(["konto", "typ"]).agg(liczba=("kwota", "size"), suma=("kwota", "sum")).reset_index(),
             hide_index=True)

if st.button("Wyczyść dane importu"):
    store.reset()
    st.rerun()
