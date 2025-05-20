import os
import sys  # Jangan lupa, biar bisa utak-atik sys.path
import platform
import logging
import time
from streamlit_autorefresh import st_autorefresh
import threading
import base64
from io import BytesIO
from datetime import datetime, timedelta
import csv
from PIL import Image, ImageDraw

import streamlit as st
import pandas as pd
import plotly.graph_objs as go
import schedule

# Tambahkan folder 'modules' ke sys.path kalau belum ada
modules_path = os.path.join(os.getcwd(), "modules")
if modules_path not in sys.path:
    sys.path.append(modules_path)

# === Cek dan impor requests ===
requests = None
try:
    import requests
except ImportError:
    st.error("Library 'requests' tidak ditemukan. Harap install library tersebut.")
    st.stop()

# === Cek dan impor pyautogui serta ImageGrab jika OS mendukung ===
pyautogui = None
ImageGrab = None
if platform.system() in ["Windows", "Darwin"] or os.environ.get('DISPLAY'):
    try:
        import pyautogui
        from PIL import ImageGrab
    except ImportError:
        logging.warning("PyAutoGUI atau Pillow (ImageGrab) tidak dapat diimpor. Fungsi screenshot mungkin tidak tersedia.")
else:
    logging.info("PyAutoGUI dan ImageGrab tidak diimpor karena tidak ada lingkungan display atau bukan Windows/Darwin.")

# === Import modul dari folder 'modules' ===
try:
    print("CWD:", os.getcwd())
    print("Isi folder modules:", os.listdir("modules"))
    
    from modules.indodax_api import (
        get_indodax_summary,
        get_trade_volume,
        fetch_all_tickers,
        load_indodax_pairs,
        get_candlestick_data,
        get_top_movers,
        estimate_open_from_summary,
        get_open_24h,
    )
    print("✅ Import modules.indodax_api berhasil!")
except Exception as e:
    print("❌ Gagal import modul indodax_api:", e)
    st.error(f"Gagal mengimpor modul Indodax API: {e}")
    st.stop()

from modules.coinmarketcap_api import get_coinmarketcap_info

try:
    from modules.indicators import apply_indicators
except ImportError as e:
    st.error(f"❌ Gagal impor modul indicators: {e}")
    st.stop()

try:
    from modules.telegram_bot import send_telegram_message, send_telegram_photo
except ImportError as e:
    st.error(f"❌ Gagal impor modul telegram_bot: {e}")
    st.stop()

try:
    from modules.signal_engine import scan_signals
except ImportError as e:
    st.error(f"❌ Gagal impor modul signal_engine: {e}")
    st.stop()

try:
    from utils.helpers import (
        hitung_rasio_bs,
        clean_and_transform_market_data,
        enrich_market_dataframe,
        get_top_movers as get_top_movers_helper,
        format_price_idr_int,
        format_number,
        format_token_amount,
        format_volume,  # ✅ WAJIB ADA!
    )
except ImportError as e:
    st.error(f"❌ Gagal impor modul helpers: {e}")
    st.stop()

# === KONFIGURASI AWAL & STATE ===
st.set_page_config(layout="wide", page_title="Read ONE Trade", page_icon="📈")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

default_session_keys = {
    "SENT_SIGNALS": [],
    "TRADE_HISTORY": [],
    "USER_LOGGED_IN": False,
    "CURRENT_PAGE": "Home",
    "startup_notified": False,
    "auto_scan_started": False,
    "last_screenshot_time": None
}

for key, default_value in default_session_keys.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# === get_app_config ===
def get_app_config():
    try:
        return {
            "exchange": st.secrets["exchange"],
            "api_key": st.secrets["api_key"],
            "api_secret": st.secrets["api_secret"],
            "telegram_token": st.secrets["telegram_token"],
            "telegram_chat_id": st.secrets["telegram_chat_id"]
        }
    except Exception as e:
        logger.error(f"Gagal memuat konfigurasi dari st.secrets: {e}")
        st.error(f"Gagal memuat konfigurasi aplikasi dari secrets.toml: {e}. Pastikan file secrets.toml sudah benar.")
        st.stop()

APP_CONFIG = get_app_config()
TELEGRAM_TOKEN = APP_CONFIG["telegram_token"]
TELEGRAM_CHAT_ID = APP_CONFIG["telegram_chat_id"]

# === FUNGSI PEMBANTU ===

# === format_price ===
def format_price(price, pair_symbol):
    try:
        price = float(price)
        pair_symbol = str(pair_symbol).lower()
        if any(currency in pair_symbol for currency in ["usdt", "usdc", "usd"]):
            return f"{price:,.8f}"
        elif "idr" in pair_symbol:
            return f"{price:,.0f}" if price >= 1 else f"{price:,.6f}"
        else:
            return f"{price:,.2f}"
    except (ValueError, TypeError):
        return str(price)

# === load_logo ===
def load_logo(logo_path="logo.png"):
    if os.path.exists(logo_path):
        try:
            logo_img = Image.open(logo_path)
            if logo_img.mode not in ("RGB", "RGBA"):
                logo_img = logo_img.convert("RGB")
            return logo_img
        except Exception as e:
            logger.warning(f"Gagal memuat logo dari file '{logo_path}': {e}. Menggunakan logo default.")
    else:
        logger.warning(f"File logo '{logo_path}' tidak ditemukan. Menggunakan logo default.")

    default_logo = Image.new("RGB", (100, 100), color="gray")
    try:
        draw = ImageDraw.Draw(default_logo)
        draw.text((15, 40), "LOGO", fill="white")
    except Exception as e:
         logger.warning(f"Gagal menggambar teks pada logo default: {e}")

    return default_logo

# === take_and_send_screenshot ===
def take_and_send_screenshot(filepath="ui_screenshot.png", caption=""):
    if ImageGrab:
        try:
            ss = ImageGrab.grab()
            ss.save(filepath)
            send_telegram_photo(filepath, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, caption=caption)
            logger.info(f"✅ Screenshot UI '{filepath}' dikirim ke Telegram.")
            os.remove(filepath)
        except Exception as e:
            logger.warning(f"❌ Gagal mengambil atau mengirim screenshot: {e}")
    else:
        logger.info("📸 Screenshot dinonaktifkan (ImageGrab tidak tersedia).")

# === periodic_screenshot_job ===
def periodic_screenshot_job(interval_seconds):
    now = datetime.now()
    if interval_seconds > 0:
        if st.session_state.last_screenshot_time is None or \
           (now - st.session_state.last_screenshot_time).total_seconds() >= interval_seconds:
            take_and_send_screenshot(caption=f"Periodic UI Screenshot ({now.strftime('%Y-%m-%d %H:%M:%S')})")
            st.session_state.last_screenshot_time = now

# === run_periodic_screenshot_scheduler ===
def run_periodic_screenshot_scheduler(interval_seconds):
    if interval_seconds > 0:
        schedule.every(interval_seconds).seconds.do(periodic_screenshot_job, interval_seconds)
        logger.info(f"Screenshot periodik diatur setiap {interval_seconds} detik.")
        while True:
            schedule.run_pending()
            time.sleep(1)
    else:
        logger.info("Screenshot periodik dinonaktifkan.")

# === plot_technical_charts ===
def plot_technical_charts(df, pair_symbol):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Candlestick'
    ))
    if 'sma' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['sma'], name='SMA', line=dict(color='orange')))
    if 'rsi' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['rsi'], name='RSI', yaxis='y2', line=dict(color='purple')))

    fig.update_layout(
        title=f'Analisis Teknikal {pair_symbol.upper()}',
        yaxis_title='Harga',
        yaxis2=dict(title='RSI', overlaying='y', side='right', showgrid=False),
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
    )
    st.plotly_chart(fig, use_container_width=True)

# === scan_selected_pair_signals ===
def scan_selected_pair_signals(pair_symbol, candle_df, summary_data):
    signals_df = scan_signals(pair_symbol, candle_df)
    if not signals_df.empty:
        st.dataframe(signals_df.tail(5))
        last_signal_info = signals_df.iloc[-1]

        signal_messages = []
        if pd.notna(last_signal_info.get('macd_signal_label')) and last_signal_info.get('macd_signal_label'):
            signal_messages.append(f"- MACD: {last_signal_info['macd_signal_label']}")
        if pd.notna(last_signal_info.get('volume_spike_label')) and last_signal_info.get('volume_spike_label'):
            signal_messages.append(f"- Volume Spike: {last_signal_info['volume_spike_label']}")

        if signal_messages:
            current_signal_text = "; ".join(signal_messages)
            signal_already_sent = any(
                s['pair'] == pair_symbol and s['signal_text'] == current_signal_text
                for s in st.session_state.SENT_SIGNALS
            )

            if not signal_already_sent:
                msg_parts = [
                    f"📢 Sinyal Terdeteksi pada {pair_symbol.upper()} ({st.session_state.get('signal_interval_display', 'N/A')})",
                    *signal_messages
                ]
                if summary_data and 'last' in summary_data:
                     msg_parts.append(f"- Harga: {format_price(summary_data['last'], pair_symbol)}")

                final_msg = "\n".join(msg_parts)

                if send_telegram_message(final_msg, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID):
                    st.success(f"Sinyal terkirim ke Telegram! 🚀\n{final_msg}")
                    st.session_state.SENT_SIGNALS.append({
                        'pair': pair_symbol,
                        'signal_text': current_signal_text,
                        'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    with open("signal_logs.txt", "a", encoding="utf-8") as f:
                        f.write(f"{datetime.now()} - {pair_symbol} - {final_msg}\n")
                else:
                    st.error("Gagal mengirim sinyal ke Telegram.")
            else:
                st.info(f"Sinyal '{current_signal_text}' untuk {pair_symbol.upper()} sudah pernah dikirim.")
    else:
        st.write("Tidak ada sinyal MACD/Volume Spike terdeteksi untuk pair ini.")

# === generate_market_signal ===
def generate_market_signal(buy_vol, sell_vol):
    if buy_vol > sell_vol * 1.2: return "STRONG BUY"
    if buy_vol > sell_vol: return "BUY"
    if buy_vol == sell_vol: return "HOLD"
    if sell_vol > buy_vol * 1.2: return "STRONG SELL"
    return "SELL"

# === get_position_suggestion ===
def get_position_suggestion(signal):
    if signal in ["STRONG BUY", "BUY"]: return "Pertimbangkan LONG"
    if signal in ["STRONG SELL", "SELL"]: return "Pertimbangkan SHORT"
    return "-"

# === style_signal_column ===
def style_signal_column(val):
    color_map = {
        "STRONG BUY": "background-color: green; color: white",
        "BUY": "background-color: lightgreen; color: black",
        "HOLD": "background-color: gray; color: white",
        "SELL": "background-color: orange; color: black",
        "STRONG SELL": "background-color: red; color: white"
    }
    return color_map.get(val, "")

# === auto_scan_all_pairs_job ===
def auto_scan_all_pairs_job(available_pairs):
    logger.info("Memulai auto-scan semua pair...")
    alerted_pairs_info = []
    for p in available_pairs:
        try:
            df = get_candlestick_data(p, tf='1h', limit=100)
            if df is not None and not df.empty:
                df_with_indicators = apply_indicators(df.copy())
                latest = df_with_indicators.iloc[-1]
                alerts = []
                if latest.get('rsi', 50) > 70: alerts.append(f"RSI Overbought ({latest['rsi']:.2f})")
                elif latest.get('rsi', 50) < 30: alerts.append(f"RSI Oversold ({latest['rsi']:.2f})")

                macd = latest.get('macd')
                macd_signal = latest.get('macd_signal')
                macd_hist = latest.get('macd_hist')
                if macd is not None and macd_signal is not None and macd_hist is not None:
                    prev_macd_hist = df_with_indicators['macd_hist'].iloc[-2] if len(df_with_indicators) > 1 else 0
                    if macd > macd_signal and prev_macd_hist <= 0:
                        alerts.append("MACD Bullish Crossover")
                    elif macd < macd_signal and prev_macd_hist >= 0:
                        alerts.append("MACD Bearish Crossover")

                if alerts:
                    signal_message = f"🚨 Sinyal Auto-Scan pada {p.upper()} (1H):\n" + "\n".join([f"- {a}" for a in alerts])
                    send_telegram_message(signal_message, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
                    alerted_pairs_info.append({'pair': p, 'signals': alerts, 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                    logger.info(f"Sinyal auto-scan terdeteksi di {p.upper()}: {', '.join(alerts)}")
        except Exception as e:
            logger.warning(f"Error saat auto-scan pair {p}: {e}")
            time.sleep(1)

    if alerted_pairs_info:
        try:
            with open("auto_scan_log.csv", "a", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                if f.tell() == 0:
                    writer.writerow(["Timestamp", "Pair", "Detected Signals"])
                for item in alerted_pairs_info:
                    writer.writerow([item['timestamp'], item['pair'], ", ".join(item['signals'])])
            logger.info(f"Hasil auto-scan disimpan ke auto_scan_log.csv. Sinyal pada: {', '.join([i['pair'] for i in alerted_pairs_info])}")
        except IOError as e:
            logger.error(f"Gagal menulis ke auto_scan_log.csv: {e}")
    else:
        logger.info("Auto-scan selesai: tidak ada sinyal baru yang signifikan terdeteksi.")
    return alerted_pairs_info

# === run_auto_scan_scheduler ===
def run_auto_scan_scheduler(available_pairs):
    schedule.every(1).hours.do(auto_scan_all_pairs_job, available_pairs)
    logger.info("Auto-scan semua pair diatur untuk berjalan setiap jam.")
    while True:
        schedule.run_pending()
        time.sleep(30)

# === TAMPILAN UI ===

# === LOGO DAN JUDUL ===
APP_LOGO = load_logo()
if APP_LOGO:
    buffered = BytesIO()
    APP_LOGO.save(buffered, format="PNG")
    base64_logo = base64.b64encode(buffered.getvalue()).decode()

    st.markdown(
        f"""
        <div style="display: flex; align-items: center; margin-bottom: 20px;">
            <img src="data:image/png;base64,{base64_logo}" width="50" style="margin-right:15px; border-radius: 5px;">
            <h1 style="display:inline; vertical-align: middle;">Read ONE Trade</h1>
        </div>
        """,
        unsafe_allow_html=True
    )
else:
    st.title("Read ONE Trade")

# === SIDEBAR ===
st.sidebar.image(APP_LOGO, width=120)
st.sidebar.header("Pengaturan Utama")

available_pairs = load_indodax_pairs()
if not available_pairs:
    st.error("Gagal mengambil daftar pair dari Indodax API. Aplikasi tidak dapat melanjutkan.")
    logger.error("Gagal memuat daftar pair Indodax.")
    st.stop()

selected_pair = st.sidebar.selectbox("🎯 Pilih Pair", available_pairs, index=available_pairs.index('btcidr') if 'btcidr' in available_pairs else 0)

# === Sidebar Pengaturan API & Telegram ===
with st.sidebar.expander("⚙️ Pengaturan API & Telegram (tersimpan)", expanded=False):
    # Mengecek apakah nilai konfigurasi ada di secrets.toml
    exchange_is_set = bool(APP_CONFIG.get("exchange"))
    api_key_is_set = bool(APP_CONFIG.get("api_key"))
    telegram_token_is_set = bool(APP_CONFIG.get("telegram_token"))
    telegram_chat_id_is_set = bool(APP_CONFIG.get("telegram_chat_id"))

    # Menentukan nilai string yang akan ditampilkan: "(Tersimpan)" jika ada, atau kosong jika tidak.
    # Nilai ini akan disamarkan menjadi titik-titik karena type="password".
    exchange_display_value = "(Tersimpan)" if exchange_is_set else ""
    api_key_display_value = "(Tersimpan)" if api_key_is_set else ""
    telegram_token_display_value = "(Tersimpan)" if telegram_token_is_set else ""
    telegram_chat_id_display_value = "(Tersimpan)" if telegram_chat_id_is_set else ""

    # Menampilkan form yang aktif (editable) dengan type="password"
    # Nilai awal form adalah string "(Tersimpan)" atau ""
    st.text_input("Exchange", value=exchange_display_value, type="password", disabled=False)
    st.text_input("API Key", value=api_key_display_value, type="password", disabled=False)
    st.text_input("Telegram Token", value=telegram_token_display_value, type="password", disabled=False)
    st.text_input("Telegram Chat ID", value=telegram_chat_id_display_value, type="password", disabled=False)

    # Menambahkan catatan penting
    st.warning("PERHATIAN: Form di atas aktif dan bisa diedit. Pengembangan multi-user & penyimpanan aman diperlukan.")
    st.info("Nilai konfigurasi yang AKTIF digunakan oleh aplikasi saat ini dimuat dari data yg tersimpan di cloud, bukan dari form ini.")

# === Sidebar Pengaturan Sinyal Pair Terpilih ===
with st.sidebar.expander("⏱️ Pengaturan Sinyal Pair Terpilih", expanded=False):
    signal_interval_options = {"5 Menit": "5min", "15 Menit": "15min", "30 Menit": "30min", "1 Jam": "1H", "4 Jam": "4H", "1 Hari": "1D"}
    selected_signal_interval_display = st.selectbox(
        "Interval Sinyal MACD & Volume", list(signal_interval_options.keys()), index=3
    )
    st.session_state.signal_interval_tf = signal_interval_options[selected_signal_interval_display]
    st.session_state.signal_interval_display = selected_signal_interval_display

    if st.button("🔄 Reset Sinyal Terkirim", key="reset_sent_signals_button"):
        st.session_state.SENT_SIGNALS = []
        st.success("✅ Daftar sinyal yang sudah terkirim berhasil di-reset.")

# === Sidebar Pengaturan Screenshot Periodik ===
with st.sidebar.expander("🖼️ Pengaturan Screenshot Periodik", expanded=False):
    screenshot_interval_map = {
        "Nonaktif": 0, "15 Menit": 900, "30 Menit": 1800, "1 Jam": 3600,
        "2 Jam": 7200, "4 Jam": 14400
    }
    selected_screenshot_interval_label = st.selectbox(
        "Interval Screenshot ke Telegram",
        options=list(screenshot_interval_map.keys()),
        index=0,
        key="screenshot_interval_label_select"
    )
    st.session_state.screenshot_interval_seconds = screenshot_interval_map[selected_screenshot_interval_label]

st.sidebar.info(f"Versi Aplikasi: 1.0.0 | Terakhir update: {datetime.now().strftime('%Y-%m-%d')}")

# === NOTIFIKASI STARTUP & INISIALISASI THREAD ===
if not st.session_state.startup_notified:
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        send_telegram_message("✅ Sistem Read ONE Trade aktif dan berjalan Lancar!", TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
        take_and_send_screenshot(caption="Tampilan Awal UI Aktif")
    st.session_state.startup_notified = True

if 'screenshot_thread' not in st.session_state and st.session_state.screenshot_interval_seconds > 0:
    screenshot_thread = threading.Thread(
        target=run_periodic_screenshot_scheduler,
        args=(st.session_state.screenshot_interval_seconds,),
        daemon=True
    )
    screenshot_thread.start()
    st.session_state.screenshot_thread = screenshot_thread
    logger.info("Thread untuk screenshot periodik dimulai.")

if not st.session_state.auto_scan_started:
    auto_scan_thread = threading.Thread(target=run_auto_scan_scheduler, args=(available_pairs,), daemon=True)
    auto_scan_thread.start()
    st.session_state.auto_scan_started = True
    logger.info("Thread untuk auto-scan semua pair dimulai.")

# === KONTEN UTAMA ===
st.subheader(f"Analisis Pair: {selected_pair.upper()}")

# === INFORMASI PAIR YANG DIPILIN SAAT INI ==================================================================
with st.expander("📊 Informasi Pair Saat Ini", expanded=True):
    try:
        summary_data = get_indodax_summary(selected_pair)
        coin_symbol = selected_pair.split("_")[0]
        cmc_info = get_coinmarketcap_info(coin_symbol)

        if summary_data:
            price_now = summary_data.get('last')
            price_low_24h = summary_data.get('low', 0)
            price_high_24h = summary_data.get('high', 0)
            raw_open = summary_data.get('open', 0)

            # Gunakan harga open valid, fallback ke low atau last jika open tidak tersedia
            price_open_24h = raw_open if raw_open > 0 else price_low_24h or price_now

            volume_idr = summary_data.get('vol_idr', 0)
            volume_token = volume_idr / price_now if price_now else 0

            if not price_now:
                st.warning(f"Ups! Harga saat ini untuk {selected_pair.upper()} belum tersedia.")
                st.stop()

            # Hitung ROI persentase yang benar, baik untuk kenaikan maupun penurunan harga
            if price_open_24h and price_open_24h > 0:
                roi_percent = ((price_now - price_open_24h) / price_open_24h) * 100
            else:
                roi_percent = 0  # fallback jika open invalid atau 0

            delta_str = f"{roi_percent:+.2f} %"
            color = "#2ecc71" if roi_percent > 0 else "#e74c3c"

            # CMC Info
            logo = cmc_info.get('logo', '')
            rank = cmc_info.get('rank', '-')
            platform = cmc_info.get('platform', '-')
            launch_year = cmc_info.get('launch_year', '-')
            total_supply = f"{int(cmc_info.get('total_supply', 0)):,}"
            circ_supply = f"{int(cmc_info.get('circulating_supply', 0)):,}"
            slug = cmc_info.get('slug', '')
            cmc_url = f"https://coinmarketcap.com/currencies/{slug}/" if slug else "#"

            # Warna badge rank
            badge_color = "#f1c40f" if rank != '-' and int(rank) <= 10 else "#bdc3c7"
            if rank != '-' and 10 < int(rank) <= 50:
                badge_color = "#95a5a6"
            elif rank != '-' and 50 < int(rank) <= 100:
                badge_color = "#cd7f32"

            # Format tampilan
            price_now_formatted = format_price_idr_int(price_now)
            price_high_24h_formatted = format_price_idr_int(price_high_24h)
            price_low_24h_formatted = format_price_idr_int(price_low_24h)
            price_open_24h_formatted = format_price_idr_int(price_open_24h)

            col1, col2 = st.columns([1, 2])

            with col1:
                st.markdown(f"""
                    <div style="font-size:clamp(14px, 1.5vw, 16px); color:#e74c3c;">Indodax Exchange</div>
                    <div style="display:flex; align-items:center;">
                        {'<img src="' + logo + '" width="30" style="margin-right:8px;">' if logo else ''}
                        <div style="font-size:clamp(20px, 2.5vw, 26px); font-weight:bold;">{selected_pair.upper()}</div>
                    </div>
                    <div style="font-size:clamp(28px, 3.5vw, 36px); font-weight:bold; color:{color};">{price_now_formatted}</div>
                    <div style="font-size:clamp(14px, 2vw, 18px); color:{color}; margin-top:5px;">{delta_str}</div>
                    <div style="font-size:clamp(12px, 1.5vw, 14px); margin-top:10px;">
                        <strong>Open 24H:</strong> {price_open_24h_formatted}<br>
                        <strong>High:</strong> {price_high_24h_formatted}<br>
                        <strong>Low:</strong> {price_low_24h_formatted}<br>
                        <strong>VOL 24H (IDR):</strong> {format_volume(volume_idr)}<br>
                        <strong>VOL 24H ({coin_symbol.upper()}):</strong> {format_token_amount(volume_token)}
                    </div>
                """, unsafe_allow_html=True)

            with col2:
                st.markdown(f"""
                    <div style="font-size:clamp(12px, 1.5vw, 14px); line-height:1.8;">
                        <table style="width:100%;">
                            <tr><td style="text-align:right;">- Tahun launching :</td><td style="padding-left:10px;">{launch_year}</td></tr>
                            <tr><td style="text-align:right;">- Rank :</td>
                                <td style="padding-left:10px;">
                                    <span style="background-color:{badge_color}; color:white; padding:2px 6px; border-radius:5px;">{rank}</span>
                                </td>
                            </tr>
                            <tr><td style="text-align:right;">- Blockchain :</td><td style="padding-left:10px;">{platform}</td></tr>
                            <tr><td style="text-align:right;">- All-time high :</td><td style="padding-left:10px;">-</td></tr>
                            <tr><td style="text-align:right;">- Total Supply :</td><td style="padding-left:10px;">{total_supply}</td></tr>
                            <tr><td style="text-align:right;">- Circulating Supply :</td><td style="padding-left:10px;">{circ_supply}</td></tr>
                        </table>
                        <br>
                        <a href="{cmc_url}" target="_blank" style="text-decoration:none;">
                            <button style="padding:5px 10px; border:none; border-radius:5px; background:#3498db; color:white; cursor:pointer;">
                                🔗 Lihat di CoinMarketCap
                            </button>
                        </a>
                    </div>
                """, unsafe_allow_html=True)

        else:
            st.warning(f"Tidak dapat mengambil informasi untuk {selected_pair}.")

    except Exception as e:
        st.error(f"Terjadi kesalahan: {e}")
#============BATAS KODE ========================================================================================================
#=====TIMER REFRES DATA DAN TAMPILAN SLIDE======================================================================================
# Daftar pair ticker
ticker_pairs = ["btc_idr", "eth_idr", "usdt_idr"]

# 🔁 Auto-refresh setiap 30 detik
count = st_autorefresh(interval=60 * 6000, limit=None, key="datarefresh")
current_index = count % len(ticker_pairs)
selected_pair = ticker_pairs[current_index]

# 🕓 Waktu terakhir refresh (biar bisa ditampilkan di UI)
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = time.strftime('%H:%M:%S')

# Tombol manual refresh
if st.button("🔄 Refresh Sekarang"):
    st.session_state.last_refresh = time.strftime('%H:%M:%S')
    st.rerun()  # Ganti dengan st.experimental_rerun() kalau masih pakai versi lama

# Tampilkan info waktu refresh terakhir
st.markdown(f"<div style='font-size:13px; color:gray;'>⏱️ Terakhir refresh: {st.session_state.last_refresh}</div>", unsafe_allow_html=True)
#==========================================================BATAS KODE =====================================================================
# === INFORMASI PAIR SLIDE ================================================================================================================
with st.expander("📊 HARGA TERKINI", expanded=True):
    selected_pairs = ["btc_idr", "eth_idr", "usdt_idr"]  # Ubah sesuai kebutuhan kamu

    def format_volume(vol):
        if vol >= 1_000_000_000:
            return f"{vol/1_000_000_000:.2f} Bn"
        elif vol >= 1_000_000:
            return f"{vol/1_000_000:.2f} M"
        elif vol >= 1_000:
            return f"{vol/1_000:.2f} K"
        return f"{vol:,.0f}"

    def format_token_amount(amount):
        if amount >= 1_000_000:
            return f"{amount/1_000_000:.2f} M"
        elif amount >= 1_000:
            return f"{amount/1_000:.2f} K"
        return f"{amount:.2f}"

    cols = st.columns(len(selected_pairs))

    for i, selected_pair in enumerate(selected_pairs):
        try:
            with cols[i]:
                summary_data = get_indodax_summary(selected_pair)
                coin_symbol = selected_pair.split("_")[0]
                cmc_info = get_coinmarketcap_info(coin_symbol)

                if summary_data:
                    price_now = summary_data.get('last')
                    price_low_24h = summary_data.get('low', 0)
                    price_high_24h = summary_data.get('high', 0)
                    raw_open = summary_data.get('open', 0)

                    price_open_24h = raw_open if raw_open > 0 else price_low_24h or price_now

                    volume_idr = summary_data.get('vol_idr', 0)
                    volume_token = volume_idr / price_now if price_now else 0

                    if not price_now:
                        st.warning(f"Ups! Harga saat ini untuk {selected_pair.upper()} belum tersedia.")
                        continue

                    roi_percent = ((price_now - price_open_24h) / price_open_24h) * 100 if price_open_24h else 0
                    delta_str = f"{roi_percent:+.2f} %"
                    color = "#00ff88" if roi_percent > 0 else "#e74c3c"

                    logo = cmc_info.get('logo', '')
                    slug = cmc_info.get('slug', '')
                    cmc_url = f"https://coinmarketcap.com/currencies/{slug}/" if slug else "#"

                    price_now_formatted = format_price_idr_int(price_now)
                    price_high_24h_formatted = format_price_idr_int(price_high_24h)
                    price_low_24h_formatted = format_price_idr_int(price_low_24h)
                    price_open_24h_formatted = format_price_idr_int(price_open_24h)

                    st.markdown(f"""
                        <div style="border:2px solid white; border-radius:12px; padding:15px; background-color:#000000; min-height:320px;">
                            <div style="font-size:14px; color:#e74c3c;">Indodax Exchange</div>
                            <div style="display:flex; align-items:center; margin-top:4px;">
                                {'<img src="' + logo + '" width="24" style="margin-right:6px;">' if logo else ''}
                                <span style="font-size:20px; font-weight:bold;">{selected_pair.upper()}</span>
                            </div>
                            <div style="font-size:28px; font-weight:bold; color:{color}; margin-top:6px;">{price_now_formatted}</div>
                            <div style="font-size:16px; color:{color};">{delta_str}</div>
                            <div style="font-size:12px; color:#ccc; margin-top:10px; line-height:1.6;">
                                <strong>Open 24H:</strong> {price_open_24h_formatted}<br>
                                <strong>High:</strong> {price_high_24h_formatted}<br>
                                <strong>Low:</strong> {price_low_24h_formatted}<br>
                                <strong>VOL 24H (IDR):</strong> {format_volume(volume_idr)}<br>
                                <strong>VOL 24H ({coin_symbol.upper()}):</strong> {format_token_amount(volume_token)}
                            </div>
                        </div>
                    """, unsafe_allow_html=True)

                else:
                    st.warning(f"Tidak dapat mengambil info untuk {selected_pair.upper()}.")
        except Exception as e:
            st.error(f"Kesalahan saat menampilkan {selected_pair.upper()}: {e}")
# ===============================================================BATAS KODE =====================================================================
# === Memuat data candlestick ===
main_placeholder = st.empty()
with main_placeholder.container():
    with st.spinner(f'Memuat data candlestick & indikator untuk {selected_pair.upper()}...'):
        candle_df = get_candlestick_data(selected_pair, tf=st.session_state.signal_interval_tf)
        if candle_df.empty:
            st.warning(f"Tidak dapat mengambil data candlestick untuk {selected_pair} dengan interval {st.session_state.signal_interval_display}.")
        else:
            candle_df_with_indicators = apply_indicators(candle_df.copy())

# === CANDLESTICK CHART ===
if not candle_df.empty and 'candle_df_with_indicators' in locals():
    with st.expander(f"📈 Candlestick Chart: {selected_pair.upper()} ({st.session_state.signal_interval_display})", expanded=True):
        chart_size_options = {"Kecil": 300, "Sedang": 450, "Besar": 600}
        selected_chart_size_label = st.selectbox("Pilih Ukuran Chart", list(chart_size_options.keys()), index=1)
        chart_height = chart_size_options[selected_chart_size_label]

        fig_candle = go.Figure()
        fig_candle.add_trace(go.Candlestick(
            x=candle_df_with_indicators.index,
            open=candle_df_with_indicators['open'], high=candle_df_with_indicators['high'],
            low=candle_df_with_indicators['low'], close=candle_df_with_indicators['close'],
            name='Candlestick', increasing_line_color='green', decreasing_line_color='red'
        ))
        fig_candle.add_trace(go.Bar(
            x=candle_df_with_indicators.index, y=candle_df_with_indicators['volume'],
            name='Volume', marker_color='rgba(0,100,255,0.3)', yaxis='y2'
        ))
        if 'sma_50' in candle_df_with_indicators.columns:
            fig_candle.add_trace(go.Scatter(
                x=candle_df_with_indicators.index, y=candle_df_with_indicators['sma_50'],
                mode='lines', name='SMA 50', line=dict(color='orange')
            ))
        if 'bb_upper' in candle_df_with_indicators.columns and 'bb_lower' in candle_df_with_indicators.columns:
             fig_candle.add_trace(go.Scatter(x=candle_df_with_indicators.index, y=candle_df_with_indicators['bb_upper'], mode='lines', name='BB Upper', line=dict(color='rgba(173,216,230,0.5)', dash='dot')))
             fig_candle.add_trace(go.Scatter(x=candle_df_with_indicators.index, y=candle_df_with_indicators['bb_lower'], mode='lines', name='BB Lower', line=dict(color='rgba(173,216,230,0.5)', dash='dot'), fill='tonexty', fillcolor='rgba(173,216,230,0.1)'))

        fig_candle.update_layout(
            title=f"Candlestick & Volume: {selected_pair.upper()} ({st.session_state.signal_interval_display})",
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            height=chart_height,
            xaxis_title="Waktu",
            yaxis_title="Harga",
            yaxis=dict(domain=[0.3, 1]),
            yaxis2=dict(domain=[0, 0.25], title="Volume", showgrid=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            plot_bgcolor='rgba(17,17,17,0.9)', paper_bgcolor='rgba(0,0,0,0)',
        )
        st.plotly_chart(fig_candle, use_container_width=True)

# === SINYAL MACD & VOLUME SPIKE (Pair Terpilih) ===
if not candle_df.empty and 'candle_df_with_indicators' in locals():
    with st.expander("📈 Sinyal MACD & Volume Spike (Pair Terpilih)", expanded=True):
        scan_selected_pair_signals(selected_pair, candle_df_with_indicators, summary_data)
else:
    st.info(f"Data candlestick untuk {selected_pair.upper()} tidak tersedia untuk pemindaian sinyal.")

# === VISUALISASI TEKNIKAL & SCANNER PAIR LAIN ===
with st.expander("📉 Visualisasi Teknikal & Scanner Pair Lain", expanded=False):
    scanner_pair = st.selectbox(
        "Pilih Pair untuk Analisis Teknikal Cepat",
        available_pairs,
        index=available_pairs.index(selected_pair)
    )
    if st.button(f"Tampilkan Analisis Teknikal untuk {scanner_pair.upper()}", key="scan_other_pair"):
        with st.spinner(f"Memuat data & indikator untuk {scanner_pair.upper()}..."):
            df_chart_scanner = get_candlestick_data(scanner_pair, tf='1H')
            if df_chart_scanner is not None and not df_chart_scanner.empty:
                df_chart_scanner_indicators = apply_indicators(df_chart_scanner.copy())
                plot_technical_charts(df_chart_scanner_indicators, scanner_pair)
            else:
                st.warning(f"Tidak dapat memuat data chart untuk {scanner_pair.upper()}.")

# === DETEKSI PASAR GLOBAL ===
# ----Fungsi Hitung Rasio
# --- Fungsi pembersih & transformasi awal data ticker ---
# --- Fungsi untuk memperkaya dataframe dengan logika bisnis ---
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

def hitung_rasio_bs(buy, sell):
    if buy == 0 and sell == 0:
        return "Seimbang (1.00)"
    ratio = buy / (sell + 1e-9)
    if ratio > 1.2:
        return f"Demand > Supply ({ratio:.2f})"
    elif ratio < 0.8:
        return f"Supply > Demand ({ratio:.2f})"
    else:
        return f"Seimbang ({ratio:.2f})"

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

with st.expander("📡 Deteksi Pasar Global", expanded=True):
    with st.spinner("Memuat data ticker semua pair..."):
        all_tickers_data = fetch_all_tickers()

    if all_tickers_data:
        df_market = clean_and_transform_market_data(all_tickers_data)
        df_market = enrich_market_dataframe(df_market)
        df_market = df_market.sort_values(by='vol_idr', ascending=False)

        required_cols = ['last', 'buy', 'sell', 'vol_idr', 'high', 'low']
        for col in required_cols:
            if col not in df_market.columns:
                logger.warning(f"Kolom '{col}' tidak ditemukan di data ticker. Ditambahkan dengan nilai default 0.")
                df_market[col] = 0

        for col in ['last', 'buy', 'sell', 'vol_idr', 'high', 'low']:
             df_market[col] = pd.to_numeric(df_market[col], errors='coerce').fillna(0)

        df_market['Harga'] = [format_price(price, pair) for price, pair in zip(df_market['last'], df_market.index)]
        df_market['Volume IDR (24j)'] = df_market['vol_idr'].apply(lambda x: f"{x:,.0f} IDR")
        df_market['Volume Buy'] = df_market['buy'].apply(lambda x: f"{x:,.0f}")
        df_market['Volume Sell'] = df_market['sell'].apply(lambda x: f"{x:,.0f}")
        df_market['Rasio B/S'] = df_market.apply(lambda x: "Demand > Supply" if x['buy'] > x['sell'] else ("Supply > Demand" if x['sell'] > x['buy'] else "Seimbang"), axis=1)
        df_market['Sinyal Pasar'] = df_market.apply(lambda x: generate_market_signal(x['buy'], x['sell']), axis=1)
        df_market['Saran Posisi'] = df_market['Sinyal Pasar'].apply(get_position_suggestion)

        df_market['Spike (%)'] = df_market.apply(
            lambda x: ((x['high'] - x['low']) / x['low'] * 100) if x['low'] > 0 else 0, axis=1
        )
        df_market['Spike (%)'] = df_market['Spike (%)'].apply(lambda x: f"{x:.2f}%")

        df_market = df_market.sort_values(by='vol_idr', ascending=False)

        cols_to_display = ['Harga', 'Volume IDR (24j)', 'Volume Buy', 'Volume Sell', 'Rasio B/S', 'Sinyal Pasar', 'Saran Posisi', 'Spike (%)']

        styled_df_market = df_market[cols_to_display].style \
            .applymap(style_signal_column, subset=['Sinyal Pasar']) \
            .set_properties(**{'text-align': 'right'}, subset=['Harga', 'Volume IDR (24j)', 'Volume Buy', 'Volume Sell', 'Spike (%)']) \
            .set_properties(**{'text-align': 'left'}, subset=['Rasio B/S', 'Saran Posisi']) \
            .set_properties(**{'text-align': 'center'}, subset=['Sinyal Pasar']) \
            .format({'Harga': '{}', 'Volume Buy': '{}', 'Volume Sell': '{}', 'Spike (%)': '{}'})
        # --- ----------------------------------------------

        st.dataframe(styled_df_market, use_container_width=True, height=600)
    else:
        st.warning("❗ Tidak ada data ticker global yang tersedia dari Indodax saat ini.")

# === TOP MOVERS (24 Jam) ===
with st.expander("🔥 Top Movers (24 Jam)", expanded=True):
    if all_tickers_data:
        top_gainers, top_losers, top_volume_movers = get_top_movers(all_tickers_data)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.write("#🚀 Top Gainers")
            if not top_gainers.empty:
                st.dataframe(top_gainers[['last', 'change']].style.format({
                    'last': lambda x: format_price(x, 'idr'),
                    'change': '{:.2f}%'
                }).set_caption("Persentase kenaikan tertinggi"))
            else:
                st.info("Tidak ada data top gainers.")
        with col2:
            st.write("#🔻 Top Losers")
            if not top_losers.empty:
                st.dataframe(top_losers[['last', 'change']].style.format({
                    'last': lambda x: format_price(x, 'idr'),
                    'change': '{:.2f}%'
                }).set_caption("Persentase penurunan terdalam"))
            else:
                st.info("Tidak ada data top losers.")
        with col3:
            st.write("#💰 Top Volume")
            if not top_volume_movers.empty:
                st.dataframe(top_volume_movers[['vol_idr']].style.format({
                    'vol_idr': '{:,.0f} IDR'
                }).set_caption("Volume perdagangan tertinggi dalam IDR"))
            else:
                st.info("Tidak ada data top volume.")
    else:
        st.warning("Tidak dapat menampilkan Top Movers karena data ticker global tidak tersedia.")

# === Footer ===
st.markdown("---")
st.markdown(f"<p style='text-align: center; color: grey;'>Develop By : OTOH © {datetime.now().year}</p>", unsafe_allow_html=True)

logger.info("Pemuatan halaman utama selesai.")
