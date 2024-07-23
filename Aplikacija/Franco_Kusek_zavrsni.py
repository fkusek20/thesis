import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import numpy as np
import streamlit as st
from binance.client import Client
from datetime import datetime
import sqlite3

st.title("Nadzorna ploča za investicijski portfelj")

# Korisnički unos za imovinu, uključujući obveznice
imovina = st.text_input("Unesite svoje imovine (odvojene zarezom, uključujući obveznice kao TLT, AGG)", "AAPL, MSFT, GOOGL, BTC-USD, ETH-USD, TLT").replace(" ", "")
# Korisnički unos za početni datum
pocetak = st.date_input("Odaberite početni datum za analizu", value=pd.to_datetime('2022-06-01'))

# Funkcija za dohvat podataka za dionice, kriptovalute i obveznice
def dohvati_podatke(imovina, pocetni_datum):
    # Podijeli imovinu na dionice/obveznice i kriptovalute
    dionice_obveznice = [sredstvo for sredstvo in imovina.split(',') if '-USD' not in sredstvo]
    kripto_imovina = [sredstvo for sredstvo in imovina.split(',') if '-USD' in sredstvo]

    # Dohvati podatke za dionice i obveznice
    podaci_dionice_obveznice = yf.download(dionice_obveznice, start=pocetni_datum)['Adj Close']
    
    # Dohvati podatke za kriptovalute
    okviri_podataka_kripto = []
    for kripto in kripto_imovina:
        kripto_id = kripto.split('-')[0] + 'USDT'
        try:
            podaci_kripto = dohvati_kripto_podatke_binance(kripto_id, pocetni_datum=str(pocetni_datum))
            okviri_podataka_kripto.append(podaci_kripto)
        except Exception as e:
            st.error(f"Pogreška pri dohvatu podataka za {kripto}: {e}")

    if okviri_podataka_kripto:
        kombinirani_podaci_kripto = pd.concat(okviri_podataka_kripto, axis=1)
        podaci = podaci_dionice_obveznice.join(kombinirani_podaci_kripto, how='outer')
    else:
        podaci = podaci_dionice_obveznice

    return podaci

# Funkcija za dohvat podataka kriptovaluta pomoću Binance API-ja
def dohvati_kripto_podatke_binance(simbol, pocetni_datum):
    klijent = Client()
    pocetni_datum = datetime.strptime(pocetni_datum, '%Y-%m-%d')
    klineovi = klijent.get_historical_klines(simbol, Client.KLINE_INTERVAL_1DAY, pocetni_datum.strftime("%d %b %Y %H:%M:%S"))
    podaci = pd.DataFrame(klineovi, columns=[
        'vremenska_oznaka', 'otvaranje', 'najviša', 'najniža', 'zatvaranje', 'volumen', 'vrijeme_zatvaranja', 'volumen_imovine_kupca',
        'broj_trgovina', 'volumen_osnovne_imovine_kupca', 'volumen_kotirane_imovine_kupca', 'zanemari'
    ])
    podaci['vremenska_oznaka'] = pd.to_datetime(podaci['vremenska_oznaka'], unit='ms')
    podaci.set_index('vremenska_oznaka', inplace=True)
    podaci = podaci[['zatvaranje']]
    podaci.columns = [simbol.replace("USDT", "-USD")]
    podaci = podaci.astype(float)
    return podaci

# Pokušaj dohvata svih podataka
try:
    svi_podaci = dohvati_podatke(imovina, pocetak)
except Exception as e:
    st.error(f"Pogreška pri dohvatu podataka: {e}")

# Čišćenje podataka uklanjanjem vrijednosti NaN
svi_podaci.dropna(inplace=True)

# Spremanje podataka u SQLite bazu podataka
def spremi_u_sqlite(df, naziv_baze='investment_portfolio.db', naziv_tablice='cijene'):
    veza = sqlite3.connect(naziv_baze)
    df.to_sql(naziv_tablice, veza, if_exists='replace', index=True)
    veza.close()

spremi_u_sqlite(svi_podaci)

# Bočna traka za unos investicijskih detalja
st.sidebar.header("Detalji investicije")
pocetna_investicija = st.sidebar.number_input("Iznos početne investicije", min_value=1000, step=100)
stopa_rasta = st.sidebar.number_input("Očekivana godišnja stopa rasta (%)", min_value=0.0, step=0.1)
tolerancija_rizika = st.sidebar.selectbox("Tolerancija na rizik", ["Niska", "Srednja", "Visoka"])
stopa_inflacije = st.sidebar.number_input("Očekivana stopa inflacije (%)", min_value=0.0, step=0.1)
bezrizicna_stopa = st.sidebar.number_input("Bezrizična stopa (%)", min_value=0.0, step=0.1, value=2.0)

# Unos udjela za svaku imovinu
st.sidebar.header("Udio imovine u portfelju (%)")
udjeli = {}
total_percentage = 0

for asset in imovina.split(','):
    udio = st.sidebar.number_input(f"{asset} udio (%)", min_value=0.0, max_value=100.0, step=0.1, value=round(100.0 / len(imovina.split(',')), 1))
    udjeli[asset] = udio
    total_percentage += udio

if total_percentage != 100.0:
    st.sidebar.error("Ukupni postotak mora biti 100%. Molimo prilagodite udjele.")

# Izračun dnevnih povrata ako podaci nisu prazni
if not svi_podaci.empty and total_percentage == 100.0:
    povrati_df = svi_podaci.pct_change().dropna()
    ponderirani_povrati = povrati_df * np.array([udjeli[asset] / 100 for asset in svi_podaci.columns])
    kumulativni_povrati = (ponderirani_povrati + 1).cumprod() - 1
    pf_kumulativni_povrati = kumulativni_povrati.sum(axis=1)

    # Dohvat S&P 500 kao referentne vrijednosti
    referentna_vrijednost = yf.download('^GSPC', start=pocetak)['Adj Close']
    referentna_vrijednost.name = 'S&P 500'
    povrati_referente = referentna_vrijednost.pct_change().dropna()
    odstupanje_referente = (povrati_referente + 1).cumprod() - 1

    # Izračun rizika portfelja
    W = np.array([udjeli[asset] / 100 for asset in povrati_df.columns])
    pf_std = np.sqrt(W.T @ povrati_df.cov() @ W)

    st.subheader("Razvoj portfelja naspram indeksa")
    # Kombiniranje i prikaz kumulativnih povrata portfelja i S&P 500 indeksa
    zajedno = pd.concat([odstupanje_referente, pf_kumulativni_povrati], axis=1)
    zajedno.columns = ['Učinak S&P 500', 'Učinak portfelja']
    st.line_chart(data=zajedno)

    st.subheader("Rizik portfelja")
    st.write(f"Rizik portfelja (Standardna devijacija): {pf_std}")

    st.subheader("Rizik referentne vrijednosti:")
    rizik_referente = povrati_referente.std()
    st.write(f"Rizik referentne vrijednosti (Standardna devijacija): {rizik_referente}")

    # Izračun Beta
    povrati_df['S&P 500'] = povrati_referente
    matrica_kovarijance = povrati_df.cov()
    beta = matrica_kovarijance.loc[:, 'S&P 500'] / povrati_referente.var()
    st.write(f"Beta: {beta}")

    # Izračun Sharpeova omjera
    visak_povrata = povrati_df.mean() - (bezrizicna_stopa / 100)
    sharpeov_omjer = visak_povrata / povrati_df.std()
    st.write(f"Sharpeov omjer: {sharpeov_omjer}")

    st.subheader("Sastav portfelja:")
    # Kružni dijagram sastava portfelja
    fig, ax = plt.subplots()
    ax.pie(W, labels=svi_podaci.columns, autopct='%1.1f%%', startangle=90)
    ax.set_title('Sastav portfelja')
    st.pyplot(fig)

    st.subheader("Statistička analiza")
    st.write("Prosjek povrata:", povrati_df.mean())
    st.write("Volatilnost:", povrati_df.std())
    st.write("Korelacije:", povrati_df.corr())

    # Izračun očekivane vrijednosti investicije prilagođene za inflaciju
    stvarna_stopa_rasta = (stopa_rasta - stopa_inflacije) / 100
    dani = (svi_podaci.index[-1] - svi_podaci.index[0]).days
    ocekivani_rast = (1 + stvarna_stopa_rasta) ** (dani / 365.25)
    ocekivana_vrijednost_investicije = pocetna_investicija * ocekivani_rast

    ocekivane_vrijednosti = pd.Series(
        pocetna_investicija * (1 + stvarna_stopa_rasta) ** ((svi_podaci.index - svi_podaci.index[0]).days / 365.25),
        index=svi_podaci.index
    )

    st.subheader("Projekcija rasta investicije")
    fig, ax = plt.subplots()
    ax.plot(kumulativni_povrati.index, pocetna_investicija * (1 + kumulativni_povrati), label='Stvarna vrijednost investicije')
    ax.plot(ocekivane_vrijednosti.index, ocekivane_vrijednosti, label='Očekivana vrijednost investicije (Prilagođeno za inflaciju)', linestyle='--')
    ax.set_xlabel('Datum')
    ax.set_ylabel('Vrijednost investicije')
    ax.legend()
    plt.xticks(rotation=45)
    st.pyplot(fig)

else:
    st.write("Nema dostupnih podataka za odabrane imovine i vremenski raspon.")
