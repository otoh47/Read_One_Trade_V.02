import os
import logging
import requests

logger = logging.getLogger(__name__)

# ========================================
# ✅ Kirim Pesan Telegram (Text)
# ========================================
def send_telegram_message(message, token, chat_id):
    """
    Kirim pesan ke Telegram menggunakan Bot API.

    Args:
        message (str): Isi pesan.
        token (str): Bot token dari BotFather.
        chat_id (str): ID chat tujuan.

    Returns:
        bool: True jika pesan berhasil dikirim, False jika gagal.
    """
    if not token or not chat_id:
        return False

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"  # Ganti ke "Markdown" jika kamu suka gaya itu
        }
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json().get("ok", False)
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Gagal mengirim pesan Telegram: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Kesalahan tak terduga saat kirim pesan: {e}")
        return False

# ========================================
# ✅ Kirim Foto ke Telegram
# ========================================
def send_telegram_photo(photo_path, token, chat_id, caption="📸 Screenshot UI"):
    """
    Kirim foto ke Telegram dengan caption.

    Args:
        photo_path (str): Path lokal ke file gambar.
        token (str): Bot token dari BotFather.
        chat_id (str): ID chat tujuan.
        caption (str): Caption foto.

    Returns:
        bool: True jika berhasil, False jika gagal.
    """
    if not os.path.exists(photo_path):
        logger.error(f"❌ Foto tidak ditemukan: {photo_path}")
        return False

    if not token or not chat_id:
        return False

    try:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        with open(photo_path, 'rb') as photo:
            files = {"photo": photo}
            data = {"chat_id": chat_id, "caption": caption}
            response = requests.post(url, files=files, data=data, timeout=20)
            response.raise_for_status()
        return response.json().get("ok", False)
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Gagal kirim foto Telegram: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Kesalahan tak terduga saat kirim foto: {e}")
        return False

# ========================================
# ⚙️ Opsional: Ambil Config dari Streamlit secrets
# ========================================
def get_current_config():
    """
    Ambil konfigurasi dari st.secrets (opsional, jika digunakan dengan Streamlit).

    Returns:
        dict: Konfigurasi (atau kosong jika gagal).
    """
    try:
        import streamlit as st
        return {
            "exchange": st.secrets["exchange"],
            "api_key": st.secrets["api_key"],
            "api_secret": st.secrets["api_secret"],
            "telegram_token": st.secrets["telegram_token"],
            "telegram_chat_id": st.secrets["telegram_chat_id"]
        }
    except ImportError:
        logger.warning("Streamlit tidak tersedia, get_current_config dilewati.")
        return {}
    except Exception as e:
        logger.error(f"Gagal mengambil konfigurasi dari st.secrets: {e}")
        return {}
