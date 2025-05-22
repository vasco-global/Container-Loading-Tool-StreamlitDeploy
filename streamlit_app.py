import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import os
import glob

# Title
st.set_page_config(layout="wide")
st.title("Price Forecasting - PROTOTYP")

# Load Data from CSV in Data folder
csv_files = glob.glob(os.path.join('Data', '*.csv'))
if csv_files:
    try:
        # Versuch: UTF-8, sonst Latin1
        try:
            data_df = pd.read_csv(csv_files[0], encoding='utf-8')
        except UnicodeDecodeError:
            data_df = pd.read_csv(csv_files[0], encoding='latin1')
        # Optionen extrahieren
        customer_options = data_df['CustomerNo.'].dropna().astype(str).unique().tolist()
        product_options = data_df['Specs'].dropna().astype(str).unique().tolist()
    except Exception as e:
        st.error(f"Fehler beim Laden der Daten: {e}")
        customer_options = []
        product_options = []
else:
    st.warning("Keine CSV-Datei im Data-Ordner gefunden.")
    customer_options = []
    product_options = []

col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    product = st.selectbox("Input Product - Hier noch Produkt oder Artikelnummer", product_options)
with col2:
    customer = st.selectbox("Input Customer", customer_options)
with col3:
    period = st.radio("Data Range", ["6 month", "12 month", "18 month"], index=0)

run = st.button("Run Algorithm")

data = {
    "Sell Price": np.random.uniform(5, 15, 10),
    "Date": pd.date_range(end=pd.Timestamp.today(), periods=10),
    "Factory": ["Factory 123"] * 10,
    "Product Price ($/m)": np.random.uniform(5, 15, 10),
    "Margin": np.random.uniform(10, 30, 10),
    "Adj. Product Price": np.random.uniform(5, 15, 10)
}

df = pd.DataFrame(data)

left, right = st.columns([3, 2])
with left:
    st.subheader("Expert View")
    st.dataframe(df)

with right:
    st.subheader(f"Graphical Visualization OPTIONAL - \"{product}\"")
    fig = px.line(df.reset_index(), x="Date", y=["Product Price ($/m)", "Sell Price", "Adj. Product Price"], labels={"value": "Price"})
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Additional Information**")
    info = {
        "Level of Accuracy (Based on data availability)": "78%",
        "Calculated Sourcing Price": "13.76 RMB",
        "Difference Calc. Sourcing Price / Hist. Sourcing Price": "-17%",
        "Average Historic Sourcing Price": "10.30 RMB",
        "Average Historic Selling Price": "19.76 RMB",
        "Average Margin": "+21.22%",
    }
    for k, v in info.items():
        st.write(f"- {k}: {v}")


st.subheader("Factory Summary")
summary = pd.DataFrame({
    "Factory": ["Factory 1", "Factory 2", "Factory 3"],
    "Est. Sourcing Price": [7.54, 7.54, 7.54],
    "Historical Margin": ["17%", "17%", "17%"],
    "Margin Fix": ["5%", "5%", "5%"],
    "Price Fix": [9.54, 9.54, 9.54]
})
st.table(summary)
