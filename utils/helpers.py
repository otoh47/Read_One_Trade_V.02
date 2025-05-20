import pandas as pd
import logging

logger = logging.getLogger(__name__)

# format_price_idr_int====================================================
def format_price_idr_int(val):
    return f"{int(val):,}".replace(",", ".")

# ---Fungsi Hitung Rasio-------------------------
def hitung_rasio_bs(buy, sell):
    if buy == 0 and sell == 0:
        return "Seimbang (1.00)"
    ratio = buy / (sell + 1e-9)  # Hindari pembagian nol
    if ratio > 1.2:
        return f"Demand > Supply ({ratio:.2f})"
    elif ratio < 0.8:
        return f"Supply > Demand ({ratio:.2f})"
    else:
        return f"Seimbang ({ratio:.2f})"
        
# --- Fungsi pembersih & transformasi awal data ticker ---
def clean_and_transform_market_data(data_dict):
    df = pd.DataFrame.from_dict(data_dict, orient='index')
    df.index.name = 'Pair'

    required_cols = ['last', 'buy', 'sell', 'vol_idr', 'high', 'low']
    for col in required_cols:
        if col not in df.columns:
            logger.warning(f"Kolom '{col}' tidak ditemukan. Ditambahkan dengan nilai default 0.")
            df[col] = 0

    for col in required_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    return df

# --- Fungsi untuk memperkaya dataframe dengan logika bisnis ---
def enrich_market_dataframe(df):
    df['Harga'] = [format_price(price, pair) for price, pair in zip(df['last'], df.index)]
    df['Volume IDR (24j)'] = df['vol_idr'].apply(lambda x: f"{x:,.0f} IDR")
    df['Volume Buy'] = df['buy'].apply(lambda x: f"{x:,.0f}")
    df['Volume Sell'] = df['sell'].apply(lambda x: f"{x:,.0f}")
    df['Rasio B/S'] = df.apply(lambda x: hitung_rasio_bs(x['buy'], x['sell']), axis=1)
    df['Sinyal Pasar'] = df.apply(lambda x: generate_market_signal(x['buy'], x['sell']), axis=1)
    df['Saran Posisi'] = df['Sinyal Pasar'].apply(get_position_suggestion)
    df['Spike (%)'] = df.apply(lambda x: ((x['high'] - x['low']) / x['low'] * 100) if x['low'] > 0 else 0, axis=1)
    df['Spike (%)'] = df['Spike (%)'].apply(lambda x: f"{x:.2f}%")
    return df

def get_top_movers(tickers):
    """Ambil top gainers, top losers dan top volume movers."""
    try:
        if not tickers:
            logger.warning("Data tickers kosong")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        df = pd.DataFrame.from_dict(tickers, orient='index')

        if df.empty:
            logger.warning("DataFrame tickers kosong")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        required_columns = ['last', 'change', 'vol_idr']
        if not all(col in df.columns for col in required_columns):
            logger.error(f"Kolom yang diperlukan tidak ada: {required_columns}. Kolom yang tersedia: {df.columns.tolist()}")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        # Konversi tipe data
        df['last'] = pd.to_numeric(df['last'], errors='coerce')
        df['change'] = pd.to_numeric(df['change'], errors='coerce')
        df['vol_idr'] = pd.to_numeric(df['vol_idr'], errors='coerce')

        # Filter NaN values
        df = df.dropna(subset=['last', 'change', 'vol_idr'])

        # Top gainers (nilai 'change' terbesar)
        top_gainers = df.sort_values(by='change', ascending=False).head(10)

        # Top losers (nilai 'change' terkecil)
        top_losers = df.sort_values(by='change').head(10)

        # Top volume movers (volume terbesar)
        top_volume = df.sort_values(by='vol_idr', ascending=False).head(10)

        logger.info(f"Kolom top_gainers sebelum return: {top_gainers.columns.tolist()}")
        return top_gainers, top_losers, top_volume

    except Exception as e:
        logger.error(f"Error dalam get_top_movers: {str(e)}", exc_info=True)
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ========FORMAT VOLUME ====================
def format_token_amount(val):
    if val >= 1e6:
        return f"{val / 1e6:.2f} Mn"
    elif val >= 1e3:
        return f"{val / 1e3:.2f} K"
    else:
        return f"{val:,.2f}"

def format_volume(val):
    if val >= 1e9:
        return f"{val / 1e9:.2f} Bn"
    elif val >= 1e6:
        return f"{val / 1e6:.2f} Mn"
    else:
        return f"{val:,.2f}"

# Format angka untuk ditampilkan dalam bentuk IDR
# Contoh: 1500000 -> '1.500.000'
# Format angka besar (volume/token) dengan satuan K/Mn/Bn
def format_price_idr_int(val):
    return f"{int(val):,}".replace(",", ".")

def format_number(val, unit_type=""):
    if val >= 1e9:
        return f"{val / 1e9:.2f} Bn"
    elif val >= 1e6:
        return f"{val / 1e6:.2f} Mn"
    elif val >= 1e3 and unit_type == "token":
        return f"{val / 1e3:.2f} K"
    else:
        return f"{val:,.2f}"
