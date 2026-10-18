<p align="center"><img src="assets/logo.png" alt="PixFund" width="240"></p>

# PixFund

Lokalna aplikacja webowa (Streamlit) do analizy portfela z eksportu XTB, wzorowana na myfund.pl, z podstawową analizą techniczną wykresów spółek. Dane zostają na Twoim komputerze.

## Funkcje
- import eksportu XTB (`.xlsx`): depozyty/wypłaty, kupno/sprzedaż, dywidendy, podatek u źródła, prowizje, odsetki
- pozycje, wycena i zyski w PLN (kursy średnie NBP z dnia poprzedzającego transakcję)
- stopy zwrotu: prosta, TWR i MWR/XIRR
- dywidendy i koszty
- wykresy z wskaźnikami AT (własne implementacje w pandas)
- notowania ze Stooq (fallback Yahoo) z lokalnym cache

## Uruchomienie
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```
Testy: `pytest -q`

## Prywatność
Pliki z eksportami XTB, `data/`, `cache/` i `cache.db` są w `.gitignore` i nie trafiają do repozytorium.
