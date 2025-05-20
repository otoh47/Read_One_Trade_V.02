import requests
import pandas as pd
import json
import logging

logger = logging.getLogger(__name__)

def load_indodax_pairs():
    url = "https://indodax.com/api/tickers"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return sorted(data["tickers"].keys())
    except Exception as e:
        logger.error(f"Gagal mengambil daftar pair: {e}")
        return []

# Fungsi untuk mendapatkan summary dari pair tertentu
def get_indodax_summary(pair):
    url = f"https://indodax.com/api/{pair}/ticker"
    try:
        response = requests.get(url)
        response.raise_for_status()
        json_data = response.json()
        if "ticker" not in json_data:
            raise ValueError(f"Pair '{pair}' tidak ditemukan atau tidak valid.")
        data = json_data["ticker"]
        return {
            "high": float(data["high"]),
            "low": float(data["low"]),
            "last": float(data["last"]),
            "open": float(data.get("open", 0)),  # Tambahkan open price 24 jam
            "vol_idr": float(data.get("vol_idr", 0)),
            "vol_btc": float(data.get("vol_btc", 0)),
            "percent": ((float(data["last"]) - float(data.get("open", 0))) / float(data.get("open", 1))) * 100 if float(data.get("open", 0)) else 0
        }
    except Exception as e:
        logger.error(f"Gagal mengambil data ticker dari Indodax: {e}")
        raise RuntimeError from e

# Fungsi untuk mendapatkan volume perdagangan buy dan sell dari pair tertentu
def get_trade_volume(pair):
    url = f"https://indodax.com/api/{pair}/trades"
    try:
        response = requests.get(url)
        response.raise_for_status()
        trades = response.json()
        df = pd.DataFrame(trades)
        df["price"] = df["price"].astype(float)
        df["amount"] = df["amount"].astype(float)
        df["type"] = df["type"].astype(str)
        buy_volume = df[df["type"] == "buy"]["amount"].sum()
        sell_volume = df[df["type"] == "sell"]["amount"].sum()
        return buy_volume, sell_volume
    except Exception as e:
        logger.error(f"Gagal mengambil data volume perdagangan: {e}")
        return 0, 0
        
# ✅ Fungsi untuk mengambil semua tickers lengkap dengan buy/sell
def fetch_all_tickers():
    url = "https://indodax.com/api/tickers"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()["tickers"]

        tickers_data = {}
        for pair, info in data.items():
            try:
                high = float(info.get("high", 0))
                low = float(info.get("low", 0))
                last = float(info.get("last", 0))
                buy = float(info.get("buy", 0))
                sell = float(info.get("sell", 0))
                vol_idr = float(info.get("vol_idr", 0))

                tickers_data[pair] = {
                    "last": last,
                    "change": ((last - low) / low * 100) if low else 0,
                    "vol_idr": vol_idr,
                    "buy": buy,
                    "sell": sell
                }

            except (ValueError, TypeError) as e:
                logger.warning(f"Gagal parsing data untuk pair {pair}: {e}")
                continue

        return tickers_data

    except Exception as e:
        logger.error(f"Gagal mengambil data tickers: {e}")
        return {}

# Fungsi untuk mendapatkan data candlestick (ohlc) dari pair tertentu
def get_candlestick_data(pair, tf='5min'):
    url = f"https://indodax.com/api/{pair}/trades"
    try:
        response = requests.get(url)
        response.raise_for_status()
        trades = response.json()
        
        if not trades:
            logger.warning(f"Data trades kosong untuk candlestick {pair}")
            return pd.DataFrame()
        
        df = pd.DataFrame(trades)
        if df.empty or not {'date', 'price', 'amount'}.issubset(df.columns):
            logger.warning(f"Data candlestick tidak lengkap untuk {pair}")
            return pd.DataFrame()

        df['date'] = pd.to_datetime(df['date'], unit='s', errors='coerce')
        df.dropna(subset=['date'], inplace=True)
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
        df.dropna(subset=['price', 'amount'], inplace=True)

        if df.empty:
            return pd.DataFrame()

        df.set_index('date', inplace=True)

        ohlc = df['price'].resample(tf).ohlc().dropna()
        ohlc['volume'] = df['amount'].resample(tf).sum()

        return ohlc.reset_index()

    except Exception as e:
        logger.error(f"Gagal mengambil data candlestick: {e}")
        return pd.DataFrame()

# Fungsi untuk mendapatkan top movers
def get_top_movers(tickers):
    try:
        top_gainers = sorted(tickers.items(), key=lambda x: x[1]["change"], reverse=True)[:10]
        top_losers = sorted(tickers.items(), key=lambda x: x[1]["change"])[:10]
        top_volume = sorted(tickers.items(), key=lambda x: x[1]["vol_idr"], reverse=True)[:10]
        return (
            pd.DataFrame(dict(top_gainers)).T,
            pd.DataFrame(dict(top_losers)).T,
            pd.DataFrame(dict(top_volume)).T,
        )
    except Exception as e:
        logger.error(f"Gagal memproses data top movers: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ==========================================================
def estimate_open_from_summary(high, low, last):
    """
    Estimasi harga open 24 jam dari data summary Indodax.
    Metode sederhana: (high + low + last) / 3
    """
    try:
        high = float(high)
        low = float(low)
        last = float(last)
        return (high + low + last) / 3 if all([high, low, last]) else last
    except Exception:
        return last

#========Cek Harga Open dari Candlestick OHLC==============
def get_open_24h(pair):
    df = get_candlestick_data(pair, tf='1D')
    if df.empty:
        return None
    open_price = df.iloc[0]['open']  # open harga di candle hari ini
    return open_price

