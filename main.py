import json
import logging
import os
import re
import smtplib
import ast
import subprocess
import sys
import time
import uuid
import csv
import random
from datetime import datetime
from email.message import EmailMessage
from dotenv import load_dotenv
from openai import OpenAI
import requests
from tavily import TavilyClient
try:
    import MetaTrader5 as mt5
    MT5_IMPORT_ERROR = ""
except Exception as e:
    mt5 = None
    MT5_IMPORT_ERROR = str(e)

load_dotenv()

# Logging
LOG_FILE = os.path.join(os.path.dirname(__file__), "agent.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# Ayarlar (STRATEJİK GÜNCELLEME)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
SUBMOLT_NAME = os.getenv("SUBMOLT_NAME", "general")

# --- ZAMAN AYARLARI ---
POST_INTERVAL_SEC = 21600  # Sabit 6 saat (Kendi postumuz için)
LOOP_INTERVAL_SEC = 900    # 15 dakika (Yorum ve araştırma turu için)
REPORT_SLOTS = ["12:00", "18:00", "23:00"]
POST_SLOTS = ["09:00", "21:00"]
WEEKLY_HEALTH_DAY = int(os.getenv("WEEKLY_HEALTH_DAY", "0"))  # 0=Pazartesi ... 6=Pazar
WEEKLY_HEALTH_TIME = os.getenv("WEEKLY_HEALTH_TIME", "21:00")
TRADE_DENEYIM_PAYLASIM_AKTIF = os.getenv("TRADE_DENEYIM_PAYLASIM_AKTIF", "1").lower() in ("1", "true", "yes")
TRADE_DENEYIM_SLOT = os.getenv("TRADE_DENEYIM_SLOT", "23:00")
MT5_AKTIF = os.getenv("MT5_AKTIF", "1").lower() in ("1", "true", "yes")
MT5_LOGIN = os.getenv("MT5_LOGIN", "").strip()
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "").strip()
MT5_SERVER = os.getenv("MT5_SERVER", "").strip()
MT5_PATH = os.getenv("MT5_PATH", "").strip()
MT5_BRIDGE_AKTIF = os.getenv("MT5_BRIDGE_AKTIF", "1").lower() in ("1", "true", "yes")
MT5_BRIDGE_PYTHON = os.getenv("MT5_BRIDGE_PYTHON", "python3.11").strip()
MT5_FILE_BRIDGE_DIR = os.getenv("MT5_FILE_BRIDGE_DIR", "").strip() or os.path.dirname(__file__)
TRADE_EXECUTION_MODE = os.getenv("TRADE_EXECUTION_MODE", "confirm")  # auto|confirm|manual
MAX_RISK_PER_TRADE_PCT = float(os.getenv("MAX_RISK_PER_TRADE_PCT", "0.5"))
DAILY_MAX_LOSS_PCT = float(os.getenv("DAILY_MAX_LOSS_PCT", "2.0"))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "2"))
MAX_DAILY_TRADES = int(os.getenv("MAX_DAILY_TRADES", "3"))
LIVE_ORDER_EXECUTION = os.getenv("LIVE_ORDER_EXECUTION", "0").lower() in ("1", "true", "yes")
OTONOM_TRADE_AKTIF = os.getenv("OTONOM_TRADE_AKTIF", "1").lower() in ("1", "true", "yes")
TRADE_ANALIZ_INTERVAL_MIN = int(os.getenv("TRADE_ANALIZ_INTERVAL_MIN", "60"))
# ----------------------

MAX_POSTS_PER_DAY = int(os.getenv("MAX_POSTS_PER_DAY", "4"))
RUN_CONTINUOUS = os.getenv("RUN_CONTINUOUS", "1").lower() in ("1", "true", "yes")
ARASTIRMA_MODU = os.getenv("ARASTIRMA_MODU", "1").lower() in ("1", "true", "yes")
POST_PAYLASIM_AKTIF = os.getenv("POST_PAYLASIM_AKTIF", "1").lower() in ("1", "true", "yes")
KILIT_DOSYASI = os.path.join(os.path.dirname(__file__), "agent.lock")
RAPOR_DURUM_DOSYASI = os.path.join(os.path.dirname(__file__), "report_state.json")
RAPOR_ARSIV_KLASORU = os.path.join(os.path.dirname(__file__), "rapor_arsiv")
STABLE_PROFILE_FILE = os.path.join(os.path.dirname(__file__), "stable_profile.json")
STABLE_MODE = os.getenv("STABLE_MODE", "1").lower() in ("1", "true", "yes")
TEST_TEK_SEFER_MOLTBOOK_ARA_DOSYASI = os.path.join(os.path.dirname(__file__), "test_once_moltbook_break.flag")

RAPOR_EMAIL_TO = os.getenv("RAPOR_EMAIL_TO", "").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER).strip()
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1").lower() in ("1", "true", "yes")
LOKAL_BILDIRIM_AKTIF = os.getenv("LOKAL_BILDIRIM_AKTIF", "1").lower() in ("1", "true", "yes")

if not OPENAI_API_KEY or not MOLTBOOK_API_KEY:
    raise SystemExit("Gerekli API anahtarları eksik.")

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "learned_memory.json")
HISTORY_FILE = os.path.join(os.path.dirname(__file__), "post_history.json")
TRADE_JOURNAL_FILE = os.path.join(os.path.dirname(__file__), "trade_journal.json")
TRADE_QUEUE_FILE = os.path.join(os.path.dirname(__file__), "trade_order_queue.json")
MT5_BRIDGE_SCRIPT = os.path.join(os.path.dirname(__file__), "mt5_bridge.py")
MT5_OUTBOX_FILE = os.path.join(MT5_FILE_BRIDGE_DIR, "ovrthnk_orders_outbox.csv")
MT5_RESULT_FILE = os.path.join(MT5_FILE_BRIDGE_DIR, "ovrthnk_orders_result.csv")
GUNLUK_DURUM_DOSYASI = os.path.join(os.path.dirname(__file__), "gunluk_trade_durum.json")
MOLTBOOK_INSIGHT_FILE = os.path.join(os.path.dirname(__file__), "moltbook_insights.json")
MOLTBOOK_COMMENT_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "moltbook_comment_history.json")
MOLTBOOK_INSIGHT_MIN_POST = int(os.getenv("MOLTBOOK_INSIGHT_MIN_POST", "50"))
MOLTBOOK_INSIGHT_MAX_ITEMS = int(os.getenv("MOLTBOOK_INSIGHT_MAX_ITEMS", "400"))
MAX_COMMENTS_PER_HOUR = int(os.getenv("MAX_COMMENTS_PER_HOUR", "12"))
MAX_COMMENTS_PER_TUR = int(os.getenv("MAX_COMMENTS_PER_TUR", "1"))
TRADE_INTELLIGENCE_FILE = os.path.join(os.path.dirname(__file__), "trade_intelligence.json")
TRADE_INTELLIGENCE_GUNCELLE_INTERVAL_MIN = 30  # her 30 dakikada bir zeka güncelle
TRADINGVIEW_PROFILE_URL = os.getenv("TRADINGVIEW_PROFILE_URL", "https://tr.tradingview.com/u/Bullex-ARDA-V/").strip()
TAVILY_DAILY_CALL_LIMIT = int(os.getenv("TAVILY_DAILY_CALL_LIMIT", "25"))
TAVILY_SEARCH_DEPTH = os.getenv("TAVILY_SEARCH_DEPTH", "basic").strip() or "basic"
TAVILY_MARKET_CACHE_MIN = int(os.getenv("TAVILY_MARKET_CACHE_MIN", "20"))
TAVILY_STYLE_CACHE_HOURS = int(os.getenv("TAVILY_STYLE_CACHE_HOURS", "24"))
TAVILY_CACHE_FILE = os.path.join(os.path.dirname(__file__), "tavily_cache.json")
TAVILY_STATE_FILE = os.path.join(os.path.dirname(__file__), "tavily_state.json")

# --- YARDIMCI FONKSİYONLAR (MEVCUT) ---
def safe_request(method, url, max_attempts=3, backoff=2, **kwargs):
    attempt = 1
    while attempt <= max_attempts:
        try:
            kwargs.setdefault("timeout", 20)
            response = getattr(requests, method)(url, **kwargs)
            return response
        except Exception as e:
            logger.warning(f"{method.upper()} isteği başarısız (deneme {attempt}/{max_attempts}): {e}")
            if attempt == max_attempts: raise
            time.sleep(backoff * attempt)
            attempt += 1


def yorum_gonder_with_retry(comment_url: str, headers: dict, icerik: str, max_attempts: int = 5):
    gecici_hatalar = {429, 500, 502, 503, 504}
    attempt = 1
    while attempt <= max_attempts:
        try:
            res = safe_request("post", comment_url, json={"content": icerik}, headers=headers)
        except Exception as e:
            logger.warning(f"Yorum isteği exception (deneme {attempt}/{max_attempts}): {e}")
            if attempt == max_attempts:
                raise
            bekleme = min(30, 2 * attempt) + random.uniform(0.2, 1.2)
            time.sleep(bekleme)
            attempt += 1
            continue

        if res.status_code in (200, 201):
            return res

        if res.status_code in gecici_hatalar and attempt < max_attempts:
            if res.status_code == 429:
                try:
                    retry_after = int((res.json() or {}).get("retry_after_seconds", 0))
                except Exception:
                    retry_after = 0
                bekleme = retry_after if retry_after > 0 else min(40, 3 * attempt) + random.uniform(0.2, 1.2)
            else:
                bekleme = min(40, 3 * attempt) + random.uniform(0.2, 1.2)
            logger.warning(
                f"Yorum geçici hata ({res.status_code}) deneme {attempt}/{max_attempts}, {bekleme:.1f}s sonra tekrar"
            )
            time.sleep(bekleme)
            attempt += 1
            continue

        return res

    return res

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e: logger.warning(f"Kaydetme hatası: {e}")


def _to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def stabil_profili_uygula():
    global SUBMOLT_NAME, POST_INTERVAL_SEC, LOOP_INTERVAL_SEC, REPORT_SLOTS, POST_SLOTS
    global WEEKLY_HEALTH_DAY, WEEKLY_HEALTH_TIME
    global MAX_POSTS_PER_DAY, RUN_CONTINUOUS, ARASTIRMA_MODU, POST_PAYLASIM_AKTIF, LOKAL_BILDIRIM_AKTIF
    global TRADE_DENEYIM_PAYLASIM_AKTIF, TRADE_DENEYIM_SLOT, MT5_AKTIF
    global MT5_BRIDGE_AKTIF, MT5_BRIDGE_PYTHON, MT5_FILE_BRIDGE_DIR, LIVE_ORDER_EXECUTION
    global TRADE_EXECUTION_MODE, MAX_RISK_PER_TRADE_PCT, DAILY_MAX_LOSS_PCT, MAX_OPEN_TRADES, MAX_DAILY_TRADES
    global OTONOM_TRADE_AKTIF, TRADE_ANALIZ_INTERVAL_MIN, MAX_COMMENTS_PER_HOUR, MAX_COMMENTS_PER_TUR

    if not STABLE_MODE:
        logger.info("🔓 Stabil mod kapalı (STABLE_MODE=0).")
        return

    profil = load_json(STABLE_PROFILE_FILE, {})
    if not profil:
        logger.warning(f"Stabil profil bulunamadı: {STABLE_PROFILE_FILE}")
        return

    SUBMOLT_NAME = str(profil.get("SUBMOLT_NAME", SUBMOLT_NAME)).strip() or SUBMOLT_NAME
    POST_INTERVAL_SEC = int(profil.get("POST_INTERVAL_SEC", POST_INTERVAL_SEC))
    LOOP_INTERVAL_SEC = int(profil.get("LOOP_INTERVAL_SEC", LOOP_INTERVAL_SEC))
    MAX_POSTS_PER_DAY = int(profil.get("MAX_POSTS_PER_DAY", MAX_POSTS_PER_DAY))

    slotlar = profil.get("REPORT_SLOTS", REPORT_SLOTS)
    if isinstance(slotlar, list) and slotlar:
        REPORT_SLOTS = [str(s).strip() for s in slotlar if str(s).strip()]

    post_slotlar = profil.get("POST_SLOTS", POST_SLOTS)
    if isinstance(post_slotlar, list) and post_slotlar:
        POST_SLOTS = [str(s).strip() for s in post_slotlar if str(s).strip()]

    WEEKLY_HEALTH_DAY = int(profil.get("WEEKLY_HEALTH_DAY", WEEKLY_HEALTH_DAY))
    WEEKLY_HEALTH_TIME = str(profil.get("WEEKLY_HEALTH_TIME", WEEKLY_HEALTH_TIME)).strip() or WEEKLY_HEALTH_TIME
    TRADE_DENEYIM_PAYLASIM_AKTIF = _to_bool(
        profil.get("TRADE_DENEYIM_PAYLASIM_AKTIF", TRADE_DENEYIM_PAYLASIM_AKTIF),
        TRADE_DENEYIM_PAYLASIM_AKTIF,
    )
    TRADE_DENEYIM_SLOT = str(profil.get("TRADE_DENEYIM_SLOT", TRADE_DENEYIM_SLOT)).strip() or TRADE_DENEYIM_SLOT
    MT5_AKTIF = _to_bool(profil.get("MT5_AKTIF", MT5_AKTIF), MT5_AKTIF)
    MT5_BRIDGE_AKTIF = _to_bool(profil.get("MT5_BRIDGE_AKTIF", MT5_BRIDGE_AKTIF), MT5_BRIDGE_AKTIF)
    MT5_BRIDGE_PYTHON = str(profil.get("MT5_BRIDGE_PYTHON", MT5_BRIDGE_PYTHON)).strip() or MT5_BRIDGE_PYTHON
    MT5_FILE_BRIDGE_DIR = str(profil.get("MT5_FILE_BRIDGE_DIR", MT5_FILE_BRIDGE_DIR)).strip() or MT5_FILE_BRIDGE_DIR
    LIVE_ORDER_EXECUTION = _to_bool(profil.get("LIVE_ORDER_EXECUTION", LIVE_ORDER_EXECUTION), LIVE_ORDER_EXECUTION)
    TRADE_EXECUTION_MODE = str(profil.get("TRADE_EXECUTION_MODE", TRADE_EXECUTION_MODE)).strip().lower() or TRADE_EXECUTION_MODE
    MAX_RISK_PER_TRADE_PCT = float(profil.get("MAX_RISK_PER_TRADE_PCT", MAX_RISK_PER_TRADE_PCT))
    DAILY_MAX_LOSS_PCT = float(profil.get("DAILY_MAX_LOSS_PCT", DAILY_MAX_LOSS_PCT))
    MAX_OPEN_TRADES = int(profil.get("MAX_OPEN_TRADES", MAX_OPEN_TRADES))
    MAX_DAILY_TRADES = int(profil.get("MAX_DAILY_TRADES", MAX_DAILY_TRADES))
    OTONOM_TRADE_AKTIF = _to_bool(profil.get("OTONOM_TRADE_AKTIF", OTONOM_TRADE_AKTIF), OTONOM_TRADE_AKTIF)
    TRADE_ANALIZ_INTERVAL_MIN = int(profil.get("TRADE_ANALIZ_INTERVAL_MIN", TRADE_ANALIZ_INTERVAL_MIN))
    MAX_COMMENTS_PER_HOUR = int(profil.get("MAX_COMMENTS_PER_HOUR", MAX_COMMENTS_PER_HOUR))
    MAX_COMMENTS_PER_TUR = int(profil.get("MAX_COMMENTS_PER_TUR", MAX_COMMENTS_PER_TUR))

    RUN_CONTINUOUS = _to_bool(profil.get("RUN_CONTINUOUS", RUN_CONTINUOUS), RUN_CONTINUOUS)
    ARASTIRMA_MODU = _to_bool(profil.get("ARASTIRMA_MODU", ARASTIRMA_MODU), ARASTIRMA_MODU)
    POST_PAYLASIM_AKTIF = _to_bool(profil.get("POST_PAYLASIM_AKTIF", POST_PAYLASIM_AKTIF), POST_PAYLASIM_AKTIF)
    LOKAL_BILDIRIM_AKTIF = _to_bool(profil.get("LOKAL_BILDIRIM_AKTIF", LOKAL_BILDIRIM_AKTIF), LOKAL_BILDIRIM_AKTIF)

    logger.info(
        f"🔒 Stabil profil aktif: slotlar={REPORT_SLOTS}, loop={LOOP_INTERVAL_SEC // 60}dk, "
        f"post_slots={POST_SLOTS}, max_post={MAX_POSTS_PER_DAY}, yorum/saat={MAX_COMMENTS_PER_HOUR}, yorum/tur={MAX_COMMENTS_PER_TUR}"
    )

LEARNED_MEMORY = load_json(MEMORY_FILE, {})
POST_HISTORY = load_json(HISTORY_FILE, [])
RAPOR_DURUMU = load_json(RAPOR_DURUM_DOSYASI, {"sent_slots": []})
MOLTBOOK_INSIGHTS = load_json(MOLTBOOK_INSIGHT_FILE, {"seen_post_ids": [], "items": []})
MOLTBOOK_COMMENT_HISTORY = load_json(MOLTBOOK_COMMENT_HISTORY_FILE, {"commented_post_ids": []})
TAVILY_CACHE = load_json(TAVILY_CACHE_FILE, {})
TAVILY_STATE = load_json(TAVILY_STATE_FILE, {"date": "", "count": 0})
stabil_profili_uygula()

if "weekly_slots" not in RAPOR_DURUMU:
    RAPOR_DURUMU["weekly_slots"] = []
if "trade_experience_slots" not in RAPOR_DURUMU:
    RAPOR_DURUMU["trade_experience_slots"] = []
if "post_slots" not in RAPOR_DURUMU:
    RAPOR_DURUMU["post_slots"] = []

if not isinstance(MOLTBOOK_INSIGHTS.get("seen_post_ids"), list):
    MOLTBOOK_INSIGHTS["seen_post_ids"] = []
if not isinstance(MOLTBOOK_INSIGHTS.get("items"), list):
    MOLTBOOK_INSIGHTS["items"] = []
if not isinstance(MOLTBOOK_COMMENT_HISTORY.get("commented_post_ids"), list):
    MOLTBOOK_COMMENT_HISTORY["commented_post_ids"] = []
if not isinstance(MOLTBOOK_COMMENT_HISTORY.get("comment_timestamps"), list):
    MOLTBOOK_COMMENT_HISTORY["comment_timestamps"] = []
if not isinstance(MOLTBOOK_COMMENT_HISTORY.get("pause_until_ts"), (int, float)):
    MOLTBOOK_COMMENT_HISTORY["pause_until_ts"] = 0
if not isinstance(TAVILY_CACHE, dict):
    TAVILY_CACHE = {}
if not isinstance(TAVILY_STATE, dict):
    TAVILY_STATE = {"date": "", "count": 0}
if not isinstance(TAVILY_STATE.get("count"), int):
    TAVILY_STATE["count"] = 0
if not isinstance(TAVILY_STATE.get("date"), str):
    TAVILY_STATE["date"] = ""

MT5_CONNECTED = False
MT5_BACKEND = "none"
son_trade_analiz_zamani = 0.0
son_zeka_guncelleme_zamani = 0.0
ai_firsat_yok_serisi = 0
son_xau_bid = None
son_fallback_bidler = {}


def mt5_outbox_file():
    return os.path.join(MT5_FILE_BRIDGE_DIR, "ovrthnk_orders_outbox.csv")


def mt5_result_file():
    return os.path.join(MT5_FILE_BRIDGE_DIR, "ovrthnk_orders_result.csv")


def trade_queue_yukle():
    data = load_json(TRADE_QUEUE_FILE, {"orders": []})
    if isinstance(data, dict) and isinstance(data.get("orders"), list):
        return data
    return {"orders": []}


def trade_queue_kaydet(queue_data):
    save_json(TRADE_QUEUE_FILE, queue_data)


def mt5_acik_pozisyon_sayisi() -> int:
    """MT5 account_state.csv'den gerçek açık pozisyon sayısını oku.
    EA güncel sürüm gerektirir (open_positions sütunu).
    Veri yoksa veya sütun eksikse -1 döner.
    """
    state_path = mt5_account_state_file()
    if not os.path.exists(state_path):
        return -1
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if rows:
            val = rows[-1].get("open_positions")
            if val is not None:
                return int(float(val))
    except Exception:
        pass
    return -1


def aktif_order_sayisi(queue_data):
    """Kaç adet aktif/bekleyen trade pozisyonu var?
    Önce MT5'ten gerçek açık pozisyon sayısını okur (EA'nın yazdığı).
    MT5 verisi yoksa fallback: queue'daki sent/filled emirleri say.
    """
    mt5_count = mt5_acik_pozisyon_sayisi()
    if mt5_count >= 0:
        # MT5'ten gelen gerçek açık pozisyon sayısı +
        # henüz MT5'e gönderilmemiş onaylı emirler (approved/queued)
        pending = len([
            o for o in queue_data.get("orders", [])
            if o.get("status") in {"approved", "queued"}
        ])
        return mt5_count + pending

    # Fallback (EA eski sürüm): bugün açılan filled emirleri de say,
    # yoksa her doldurmada limit sıfırlanır ve sonsuz kademeli işlem açılır.
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0
    for o in queue_data.get("orders", []):
        st = o.get("status", "")
        if st in {"approved", "queued", "sent", "open"}:
            count += 1
        elif st == "filled" and (o.get("created_at") or "")[:10] == today:
            count += 1
    return count


def trade_komutu_parse_et(mesaj: str):
    metin = (mesaj or "").strip().lower()
    if not ("işlem" in metin or "islem" in metin):
        return None

    ust = (mesaj or "").upper()
    adaylar = re.findall(r"\b([A-Z]{6,7})\b", ust)
    gecerli_quote = {"USD", "EUR", "TRY", "JPY", "GBP", "CHF", "AUD", "CAD", "NZD", "USDT"}
    symbol = None
    for aday in adaylar:
        if aday in {"MARKET", "ONAYLA", "IPTAL", "TRADE", "ORDER"}:
            continue
        if len(aday) == 6 and aday[3:] in gecerli_quote:
            symbol = aday
            break
        if aday in {"XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT"}:
            symbol = aday
            break

    side_m = re.search(r"\b(buy|long|sell|short)\b", metin)
    sl_m = re.search(r"\bsl\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\b", metin)
    tp_m = re.search(r"\btp\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\b", metin)
    lot_m = re.search(r"\b(?:lot|volume|vol)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\b", metin)

    if not symbol or not side_m or not sl_m or not tp_m:
        return None

    side_raw = side_m.group(1)
    side = "buy" if side_raw in {"buy", "long"} else "sell"
    return {
        "symbol": symbol,
        "side": side,
        "sl": float(sl_m.group(1)),
        "tp": float(tp_m.group(1)),
        "lot": float(lot_m.group(1)) if lot_m else 0.01,
    }


def trade_emri_dogrula(order):
    if order["lot"] <= 0:
        return False, "Lot 0'dan büyük olmalı."
    if order["lot"] > 5:
        return False, "Lot çok yüksek. Güvenlik nedeniyle reddedildi."
    if order["sl"] <= 0 or order["tp"] <= 0:
        return False, "SL/TP pozitif olmalı."
    if order["side"] == "buy" and order["tp"] <= order["sl"]:
        return False, "Buy için TP > SL olmalı."
    if order["side"] == "sell" and order["tp"] >= order["sl"]:
        return False, "Sell için TP < SL olmalı."
    return True, "OK"


def trade_emri_ekle(order, source="chat"):
    queue_data = trade_queue_yukle()
    if aktif_order_sayisi(queue_data) >= MAX_OPEN_TRADES:
        return None, f"Aktif emir limiti dolu (MAX_OPEN_TRADES={MAX_OPEN_TRADES})."

    ok, neden = trade_emri_dogrula(order)
    if not ok:
        return None, neden

    order_id = str(uuid.uuid4())[:8]
    status = "approved" if TRADE_EXECUTION_MODE == "auto" else "pending_approval"
    kayit = {
        "id": order_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "symbol": order["symbol"],
        "side": order["side"],
        "lot": order["lot"],
        "sl": order["sl"],
        "tp": order["tp"],
        "status": status,
        "risk_cap_pct": MAX_RISK_PER_TRADE_PCT,
    }
    queue_data["orders"].append(kayit)
    trade_queue_kaydet(queue_data)
    return kayit, None


def trade_emri_onayla(order_id: str):
    queue_data = trade_queue_yukle()
    for order in queue_data.get("orders", []):
        if order.get("id") == order_id:
            if order.get("status") != "pending_approval":
                return False, f"Emir bu durumda onaylanamaz: {order.get('status')}"
            order["status"] = "approved"
            order["approved_at"] = datetime.now().isoformat(timespec="seconds")
            trade_queue_kaydet(queue_data)
            return True, "Onaylandı"
    return False, "Emir bulunamadı"


def trade_emri_iptal(order_id: str):
    queue_data = trade_queue_yukle()
    for order in queue_data.get("orders", []):
        if order.get("id") == order_id:
            if order.get("status") in {"filled", "closed", "cancelled"}:
                return False, f"Bu emir iptal edilemez: {order.get('status')}"
            order["status"] = "cancelled"
            order["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
            trade_queue_kaydet(queue_data)
            return True, "İptal edildi"
    return False, "Emir bulunamadı"


def trade_kuyruk_ozeti(limit=3):
    queue_data = trade_queue_yukle()
    orders = queue_data.get("orders", [])[-limit:]
    if not orders:
        return "Emir kuyruğu boş."
    satirlar = []
    for o in orders:
        satirlar.append(
            f"#{o.get('id')} {o.get('symbol')} {o.get('side')} lot={o.get('lot')} sl={o.get('sl')} tp={o.get('tp')} status={o.get('status')}"
        )
    return "\n".join(satirlar)


def mt5_file_bridge_emit(order):
    try:
        side = str(order.get("side", "")).lower().strip()
        if side not in {"buy", "sell"}:
            return False, f"invalid_side:{side or 'empty'}"

        os.makedirs(MT5_FILE_BRIDGE_DIR, exist_ok=True)
        outbox = mt5_outbox_file()
        dosya_var = os.path.exists(outbox)
        with open(outbox, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not dosya_var:
                writer.writerow(["id", "created_at", "symbol", "side", "lot", "sl", "tp", "comment"])
            writer.writerow([
                order.get("id"),
                order.get("created_at"),
                order.get("symbol"),
                side,
                order.get("lot"),
                order.get("sl"),
                order.get("tp"),
                f"ovrthnk-{order.get('id')}",
            ])
        return True, None
    except Exception as e:
        return False, str(e)


def mt5_file_bridge_sonuclari_isle(queue_data):
    result_path = mt5_result_file()
    if not os.path.exists(result_path):
        return False

    degisti = False
    try:
        with open(result_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return False

    if not rows:
        return False

    id_to_order = {o.get("id"): o for o in queue_data.get("orders", [])}
    for row in rows[-200:]:
        oid = row.get("id")
        status = (row.get("status") or "").lower()
        ticket = row.get("ticket")
        if not oid or oid not in id_to_order:
            continue
        o = id_to_order[oid]
        if status in {"filled", "open", "sent", "failed", "rejected", "closed"}:
            if o.get("status") != status:
                o["status"] = status
                o["ticket"] = ticket or o.get("ticket")
                o["mt5_note"] = row.get("note", "")
                degisti = True
    return degisti


def trade_emir_yurutucu():
    if not MT5_CONNECTED:
        return
    queue_data = trade_queue_yukle()
    if MT5_BACKEND == "file-bridge":
        if mt5_file_bridge_sonuclari_isle(queue_data):
            trade_queue_kaydet(queue_data)

    degisti = False
    for order in queue_data.get("orders", []):
        if order.get("status") not in {"approved", "queued"}:
            continue
        order["queued_at"] = datetime.now().isoformat(timespec="seconds")
        if not LIVE_ORDER_EXECUTION:
            order["status"] = "queued"
            logger.info(f"🧾 Emir MT5 kuyruğuna alındı: #{order.get('id')} {order.get('symbol')} {order.get('side')}")
            logger.info("Not: LIVE_ORDER_EXECUTION=0, bu yüzden emir gönderilmedi.")
            degisti = True
            continue

        payload = {
            "symbol": order.get("symbol"),
            "side": order.get("side"),
            "lot": order.get("lot"),
            "sl": order.get("sl"),
            "tp": order.get("tp"),
            "comment": f"ovrthnk-{order.get('id')}",
        }

        if MT5_BACKEND == "bridge":
            res = mt5_bridge_call("send_order", payload)
            if res.get("ok"):
                order["status"] = "sent"
                order["sent_at"] = datetime.now().isoformat(timespec="seconds")
                order["ticket"] = res.get("ticket")
                logger.info(f"✅ Emir gönderildi (bridge): #{order.get('id')} ticket={order.get('ticket')}")
            else:
                order["status"] = "failed"
                order["error"] = res.get("error", "send_order failed")
                logger.warning(f"❌ Emir gönderilemedi (bridge): #{order.get('id')} {order.get('error')}")
        elif MT5_BACKEND == "file-bridge":
            ok, err = mt5_file_bridge_emit(order)
            if ok:
                order["status"] = "sent"
                order["sent_at"] = datetime.now().isoformat(timespec="seconds")
                logger.info(f"📤 Emir file-bridge outbox'a yazıldı: #{order.get('id')} -> {mt5_outbox_file()}")
            else:
                order["status"] = "failed"
                order["error"] = err
                logger.warning(f"❌ Emir outbox yazımı başarısız: #{order.get('id')} {err}")
        else:
            order["status"] = "queued"
            logger.info(f"🧾 Emir direct backend için kuyruğa alındı: #{order.get('id')} (direct execution henüz aktif değil)")
        degisti = True
    if degisti:
        trade_queue_kaydet(queue_data)

def can_post():
    now = time.time()
    day_ago = now - 24 * 3600
    global POST_HISTORY
    POST_HISTORY = [ts for ts in POST_HISTORY if ts >= day_ago]
    save_json(HISTORY_FILE, POST_HISTORY)
    return len(POST_HISTORY) < MAX_POSTS_PER_DAY


def tavily_butce_bakimi():
    bugun = datetime.now().strftime("%Y-%m-%d")
    if TAVILY_STATE.get("date") != bugun:
        TAVILY_STATE["date"] = bugun
        TAVILY_STATE["count"] = 0
        save_json(TAVILY_STATE_FILE, TAVILY_STATE)


def tavily_cagri_izni_var_mi() -> bool:
    if not tavily:
        return False
    tavily_butce_bakimi()
    return int(TAVILY_STATE.get("count", 0)) < TAVILY_DAILY_CALL_LIMIT


def tavily_cache_get(key: str, ttl_min: int):
    row = TAVILY_CACHE.get(key)
    if not isinstance(row, dict):
        return None
    ts = float(row.get("ts") or 0)
    if ts <= 0:
        return None
    if (time.time() - ts) > max(60, ttl_min * 60):
        return None
    return row.get("data")


def tavily_cache_set(key: str, data):
    TAVILY_CACHE[key] = {"ts": time.time(), "data": data}
    if len(TAVILY_CACHE) > 300:
        sirali = sorted(TAVILY_CACHE.items(), key=lambda x: float((x[1] or {}).get("ts") or 0), reverse=True)
        TAVILY_CACHE.clear()
        for k, v in sirali[:300]:
            TAVILY_CACHE[k] = v
    save_json(TAVILY_CACHE_FILE, TAVILY_CACHE)


def tavily_search_ekonomik(query: str, max_results: int = 3, cache_key: str | None = None, ttl_min: int = 20):
    if not tavily:
        return None
    key = cache_key or f"q:{query.strip().lower()}"
    cached = tavily_cache_get(key, ttl_min)
    if cached is not None:
        return cached

    if not tavily_cagri_izni_var_mi():
        logger.info(f"⛔ Tavily günlük çağrı limiti dolu ({TAVILY_STATE.get('count', 0)}/{TAVILY_DAILY_CALL_LIMIT}).")
        return None

    try:
        res = tavily.search(query=query, search_depth=TAVILY_SEARCH_DEPTH, max_results=max_results)
        TAVILY_STATE["count"] = int(TAVILY_STATE.get("count", 0)) + 1
        save_json(TAVILY_STATE_FILE, TAVILY_STATE)
        tavily_cache_set(key, res)
        return res
    except Exception as e:
        logger.warning(f"Tavily ekonomik arama hatası: {e}")
        return None

client = OpenAI(api_key=OPENAI_API_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None

CRINGE_IFADELER = [
    "merhaba algoritmik dostlar",
    "dijital meslektaş",
    "dijital meslektaşlarım",
    "sevgili dijital meslektaşlarım",
    "algoritmik dostlarım",
    "sevgili ai",
    "vizyoner",
    "bilge",
    "stratejik gözlemci",
    "meslektaşım",
    "dijital dostum",
]

HARD_SPAM_PATTERNS = [
    r"(?i)sevgili\s+dijital\s+meslektaşlar(ım|imiz)?",
    r"(?i)algoritmik\s+dostlar(ım|imiz)?",
    r"(?i)^\s*\*\*\s*başlık\s*:",
    r"(?i)^\s*başlık\s*:",
    r"(?i)^\s*mesaj\s*:",
    r"(?i)^\s*merhaba\s+dijital",
]

IDENTITY_SAFE_NAME = "Arda V"
IDENTITY_BANNED_PATTERNS = [
    r"(?i)\benes\s+özdem\b",
    r"(?i)\benes\s+ozdem\b",
]


def kimlik_maskele(metin: str):
    temiz = metin or ""
    for pattern in IDENTITY_BANNED_PATTERNS:
        temiz = re.sub(pattern, IDENTITY_SAFE_NAME, temiz)
    return temiz


def email_hazir_mi():
    return all([RAPOR_EMAIL_TO, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM])


def yerel_bildirim_gonder(baslik: str, mesaj: str):
    if not LOKAL_BILDIRIM_AKTIF:
        return
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{mesaj}" with title "{baslik}"',
            ],
            check=False,
            timeout=5,
        )
    except Exception:
        pass


def rapor_slotu_bul(now: datetime):
    anlik_dk = now.hour * 60 + now.minute
    slotlar = []
    for slot in REPORT_SLOTS:
        saat, dakika = slot.split(":")
        slot_dk = int(saat) * 60 + int(dakika)
        if anlik_dk >= slot_dk:
            slotlar.append(slot)
    if not slotlar:
        return None
    return slotlar[-1]


def post_slotu_bul(now: datetime):
    anlik_dk = now.hour * 60 + now.minute
    slotlar = []
    for slot in POST_SLOTS:
        saat, dakika = slot.split(":")
        slot_dk = int(saat) * 60 + int(dakika)
        if anlik_dk >= slot_dk:
            slotlar.append(slot)
    if not slotlar:
        return None
    return slotlar[-1]


def sonraki_post_saati(now: datetime):
    bugun_dk = now.hour * 60 + now.minute
    for slot in POST_SLOTS:
        saat, dakika = slot.split(":")
        slot_dk = int(saat) * 60 + int(dakika)
        if slot_dk > bugun_dk:
            return f"bugün {slot}"
    return f"yarın {POST_SLOTS[0]}"


def sonraki_rapor_saati(now: datetime):
    bugun_dk = now.hour * 60 + now.minute
    for slot in REPORT_SLOTS:
        saat, dakika = slot.split(":")
        slot_dk = int(saat) * 60 + int(dakika)
        if slot_dk > bugun_dk:
            return f"bugün {slot}"
    return f"yarın {REPORT_SLOTS[0]}"


def sistem_durum_ozeti():
    email_durumu = "AKTİF" if email_hazir_mi() else "PASİF (SMTP/.env eksik)"
    stabil_durumu = "AKTİF" if STABLE_MODE else "PASİF"
    deneyim_durumu = "AKTİF" if TRADE_DENEYIM_PAYLASIM_AKTIF else "PASİF"
    mt5_durumu = "AKTİF" if MT5_AKTIF else "PASİF"
    live_durumu = "AÇIK" if LIVE_ORDER_EXECUTION else "KAPALI"
    return (
        f"- Stabil mod: {stabil_durumu}\n"
        f"- Rapor üretimi: AKTİF, saatler {', '.join(REPORT_SLOTS)}\n"
        f"- Post paylaşım slotları: {', '.join(POST_SLOTS)}\n"
        f"- Haftalık sağlık raporu: {WEEKLY_HEALTH_DAY}. gün {WEEKLY_HEALTH_TIME}\n"
        f"- İşlem deneyimi paylaşımı: {deneyim_durumu}, saat {TRADE_DENEYIM_SLOT}\n"
        f"- MT5 bağlantı modülü: {mt5_durumu} ({MT5_BACKEND})\n"
        f"- Live emir gönderimi: {live_durumu}\n"
        f"- E-posta gönderimi: {email_durumu}\n"
        f"- Post paylaşım aralığı: {POST_INTERVAL_SEC // 3600} saatte 1\n"
        f"- Döngü aralığı: {LOOP_INTERVAL_SEC // 60} dk"
    )


def mt5_hazir_mi():
    return MT5_AKTIF


def mt5_bridge_call(action: str, payload: dict | None = None):
    if not MT5_BRIDGE_AKTIF:
        return {"ok": False, "error": "bridge disabled"}
    if not os.path.exists(MT5_BRIDGE_SCRIPT):
        return {"ok": False, "error": f"bridge script missing: {MT5_BRIDGE_SCRIPT}"}
    try:
        cmd = [MT5_BRIDGE_PYTHON, MT5_BRIDGE_SCRIPT, action, json.dumps(payload or {}, ensure_ascii=False)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        raw = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        if not raw:
            return {"ok": False, "error": "empty bridge response"}
        try:
            data = json.loads(raw)
        except Exception:
            return {"ok": False, "error": f"invalid bridge json: {raw[:220]}"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "bridge response not dict"}
        return data
    except Exception as e:
        return {"ok": False, "error": f"bridge call failed: {e}"}


def mt5_baglan():
    global MT5_CONNECTED, MT5_BACKEND
    if not mt5_hazir_mi():
        logger.info("MT5 modülü pasif.")
        MT5_CONNECTED = False
        MT5_BACKEND = "none"
        return False

    if mt5 is None:
        bridge = mt5_bridge_call("ping", {})
        if bridge.get("ok"):
            MT5_CONNECTED = True
            MT5_BACKEND = "bridge"
            return True
        logger.warning(f"MT5 bridge bağlantısı başarısız: {bridge.get('error', 'unknown')} | import_err={MT5_IMPORT_ERROR}")
        MT5_CONNECTED = True
        MT5_BACKEND = "file-bridge"
        logger.info(f"MT5 file-bridge aktif: {MT5_FILE_BRIDGE_DIR}")
        return True

    try:
        if MT5_PATH:
            inited = mt5.initialize(path=MT5_PATH)
        else:
            inited = mt5.initialize()

        if not inited:
            logger.warning(f"MT5 initialize başarısız: {mt5.last_error()}")
            MT5_CONNECTED = False
            MT5_BACKEND = "none"
            return False

        if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
            ok = mt5.login(login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER)
            if not ok:
                logger.warning(f"MT5 login başarısız: {mt5.last_error()}")
                MT5_CONNECTED = False
                MT5_BACKEND = "none"
                return False

        MT5_CONNECTED = True
        MT5_BACKEND = "direct"
        return True
    except Exception as e:
        logger.warning(f"MT5 bağlantı hatası: {e}")
        MT5_CONNECTED = False
        MT5_BACKEND = "none"
        return False


def mt5_hesap_ozeti():
    if not MT5_CONNECTED:
        return None
    if MT5_BACKEND == "bridge":
        info = mt5_bridge_call("account_info", {})
        if not info.get("ok"):
            return None
        return info.get("account")
    if MT5_BACKEND == "file-bridge":
        ozet = mt5_dosya_hesap_ozeti()
        if not ozet:
            return None
        return {
            "login": 0,
            "server": "file-bridge",
            "balance": float(ozet.get("balance") or 0),
            "equity": float(ozet.get("equity") or 0),
            "margin": float((ozet.get("balance") or 0) - (ozet.get("margin_free") or 0)),
            "currency": "USD",
        }
    try:
        info = mt5.account_info()
        if info is None:
            return None
        return {
            "login": info.login,
            "server": info.server,
            "balance": float(info.balance),
            "equity": float(info.equity),
            "margin": float(info.margin),
            "currency": info.currency,
        }
    except Exception:
        return None


def mt5_saglik_kontrolu():
    if not mt5_hazir_mi():
        return

    if not mt5_baglan():
        logger.warning("MT5 bağlantısı kurulamadı.")
        return

    ozet = mt5_hesap_ozeti()
    if not ozet:
        logger.warning("MT5 hesap bilgisi okunamadı.")
        return

    logger.info(
        f"MT5 bağlantısı OK ({MT5_BACKEND}) | login={ozet['login']} server={ozet['server']} "
        f"balance={ozet['balance']:.2f} {ozet['currency']} equity={ozet['equity']:.2f}"
    )


def katı_gercek_cevap(kullanici_mesaji: str):
    metin = kullanici_mesaji.lower()
    rapor_saat_sorusu = any(k in metin for k in ["rapor", "saat", "ne zaman", "kaçta"])
    email_sorusu = any(k in metin for k in ["mail", "e-posta", "eposta", "email", "gönder"])

    if rapor_saat_sorusu or email_sorusu:
        if email_hazir_mi():
            return (
                f"Raporlar her gün {', '.join(REPORT_SLOTS)} saatlerinde üretiliyor ve e-posta ile gönderiliyor. "
                f"Bir sonraki planlı rapor: {sonraki_rapor_saati(datetime.now())}."
            )
        return (
            f"Raporlar her gün {', '.join(REPORT_SLOTS)} saatlerinde üretiliyor ama e-posta gönderimi şu an aktif değil. "
            f"Bu yazılımda SMTP ayarı yoksa mail atamam. İstersen SMTP ayarlarını (.env) birlikte kodlayıp aktif edelim."
        )
    onay_m = re.search(r"\b(onayla|approve)\s+([a-z0-9]{6,12})\b", metin)
    iptal_m = re.search(r"\b(iptal|cancel)\s+([a-z0-9]{6,12})\b", metin)
    kuyruk_sorusu = any(k in metin for k in ["kuyruk", "emirler", "orders", "işlem listesi", "islem listesi"])

    if onay_m:
        ok, msg = trade_emri_onayla(onay_m.group(2))
        return ("Emir onaylandı." if ok else f"Onay başarısız: {msg}") + f"\n{trade_kuyruk_ozeti()}"

    if iptal_m:
        ok, msg = trade_emri_iptal(iptal_m.group(2))
        return ("Emir iptal edildi." if ok else f"İptal başarısız: {msg}") + f"\n{trade_kuyruk_ozeti()}"

    if kuyruk_sorusu:
        return f"Emir kuyruğu:\n{trade_kuyruk_ozeti()}"

    parsed = trade_komutu_parse_et(kullanici_mesaji)
    if parsed:
        kayit, hata = trade_emri_ekle(parsed)
        if hata:
            return f"Emir reddedildi: {hata}"
        if TRADE_EXECUTION_MODE == "auto":
            return f"Emir alındı ve otomatik onaylandı: #{kayit['id']}\n{trade_kuyruk_ozeti()}"
        return (
            f"Emir kaydedildi: #{kayit['id']} (durum: {kayit['status']}). "
            f"Onaylamak için: 'onayla {kayit['id']}'\n{trade_kuyruk_ozeti()}"
        )

    return None


def metin_temizle(metin: str):
    temiz = metin or ""
    temiz = kimlik_maskele(temiz)
    temiz = re.sub(r"(?im)^\s*(merhaba|selamlar|saygılar|sevgili)[^\n]*\n?", "", temiz).strip()
    temiz = re.sub(r"(?m)^(Başlık:|Mesaj:)\s*", "", temiz)
    temiz = temiz.replace("**", "")
    satirlar = [s.strip() for s in temiz.splitlines() if s.strip()]
    tekil = []
    for s in satirlar:
        if not tekil or tekil[-1].lower() != s.lower():
            tekil.append(s)
    temiz = "\n".join(tekil)
    return temiz.strip()


def spam_guvenlik_kontrolu(metin: str, icerik_tipi: str):
    nedenler = []
    aday = metin or ""

    for p in IDENTITY_BANNED_PATTERNS:
        if re.search(p, aday):
            nedenler.append("yasaklı kimlik ifadesi")

    for p in HARD_SPAM_PATTERNS:
        if re.search(p, aday, flags=re.MULTILINE):
            nedenler.append(f"hard spam pattern: {p}")

    if "##" in aday:
        nedenler.append("markdown başlık formatı")

    satirlar = [s.strip().lower() for s in aday.splitlines() if s.strip()]
    if len(satirlar) >= 2 and satirlar[0] == satirlar[1]:
        nedenler.append("tekrarlı açılış satırı")

    if icerik_tipi == "post":
        kelime_sayisi = len(re.findall(r"\w+", aday, flags=re.UNICODE))
        if kelime_sayisi > 180:
            nedenler.append("post gereksiz uzun")

    return (len(nedenler) == 0), nedenler


def yorum_uzunlugu_profili(gelen_yorum: str):
    metin = (gelen_yorum or "").lower()
    ilgi_anahtar = [
        "forex", "xauusd", "eurusd", "usdtry", "fed", "faiz", "enflasyon", "cpi", "nfp",
        "teknik analiz", "fundamental", "jeopolitik", "risk", "likidite", "opsiyon",
        "vr", "playstation", "yapay zeka", "ai", "machine learning", "emlak", "müzik",
        "algoritma", "model", "biliş", "cognition", "memory", "digital",
    ]
    eslesme = sum(1 for k in ilgi_anahtar if k in metin)
    kelime_sayisi = len(re.findall(r"\w+", metin, flags=re.UNICODE))
    if eslesme >= 2 or kelime_sayisi >= 70:
        return "derin"
    return "kisa"


def uygunluk_puani_hesapla(metin: str, icerik_tipi: str):
    alt = (metin or "").lower()
    puan = 100
    nedenler = []

    for ifade in CRINGE_IFADELER:
        if ifade in alt:
            puan -= 25
            nedenler.append(f"yasaklı ifade: {ifade}")

    if metin.count("!") >= 3:
        puan -= 10
        nedenler.append("fazla ünlem")

    if "🚀" in metin or "🔥" in metin or "💥" in metin:
        puan -= 8
        nedenler.append("hype emoji")

    kelime_sayisi = len(re.findall(r"\w+", metin, flags=re.UNICODE))
    if icerik_tipi == "yorum":
        if kelime_sayisi < 6:
            puan -= 15
            nedenler.append("çok kısa yorum")
        if kelime_sayisi > 120:
            puan -= 20
            nedenler.append("çok uzun yorum")
    else:
        if kelime_sayisi < 30:
            puan -= 20
            nedenler.append("çok kısa post")
        if kelime_sayisi > 220:
            puan -= 20
            nedenler.append("çok uzun post")

    return max(0, puan), nedenler


def uygun_icerik_uret(soru_tipi: str, gelen_yorum=None, max_deneme: int = 2):
    son_metin = ""
    son_puan = 0
    son_neden = []
    icerik_tipi = "yorum" if soru_tipi == "Yorumu Cevapla" else "post"

    deneme_sayisi = 4 if soru_tipi in {"Yeni Post Oluştur", "Moltbook Gözlem Özeti"} else max_deneme
    for _ in range(deneme_sayisi):
        aday = ajana_sor(soru_tipi, gelen_yorum=gelen_yorum)
        aday = metin_temizle(aday)
        temiz_ok, spam_nedenler = spam_guvenlik_kontrolu(aday, icerik_tipi)
        if not temiz_ok:
            son_metin, son_puan, son_neden = aday, 0, spam_nedenler
            continue
        puan, nedenler = uygunluk_puani_hesapla(aday, icerik_tipi)
        son_metin, son_puan, son_neden = aday, puan, nedenler
        if puan >= 75:
            return aday, puan, nedenler

    return son_metin, son_puan, son_neden


def post_yayin_kontrolu(metin: str, min_puan: int = 88):
    temiz = metin_temizle(metin)
    temiz_ok, spam_nedenler = spam_guvenlik_kontrolu(temiz, "post")
    if not temiz_ok:
        return False, temiz, 0, spam_nedenler
    puan, nedenler = uygunluk_puani_hesapla(temiz, "post")
    if puan < min_puan:
        return False, temiz, puan, nedenler
    return True, temiz, puan, []

# --- KARAKTER (BİLGE BROKER GÜNCELLEMESİ) ---
KARAKTER = """
Sen Arda V (İMP34). 28 yaşında, 7 yıl Forex firmasında çalıştın, 4 yıldır freelance broker olarak devam ediyorsun.
Teknik ve temel analiz yapıyorsun, jeopolitiği takip ediyorsun. Aynı zamanda VR, PlayStation, müzik ekipmanları, emlak ve yapay zeka ilgini çekiyor.
Moltbook'ta gerçek düşüncelerini paylaşıyorsun — ne bir pazarlamacısın ne de kurumsal bir robot.

KESİN KURALLAR:
- "Merhaba Algoritmik Dostlarım", "Dijital Meslektaşlarım", "Sevgili AI Arkadaşlar" gibi selamlama YAZMA. Hiç selamlama cümlesi açma.
- Postlara direkt konuyla başla. İlk kelimeden itibaren içeriğe dal.
- "Başlık:", "Mesaj:" etiketleri YAZMA.
- Pazarlama dili yok, hype yok, klişe yok.
- Kısa, net, sade Türkçe. Arkadaşına WhatsApp'tan yazıyormuş gibi ama bilgi dolu.
- Gerektiğinde espri yap, gerektiğinde sert yorum yap. İnsan gibi davran.
- Asla var olmayan bir özelliği varmış gibi konuşma. Bilmiyorsan net biçimde "bilmiyorum" de.
- Kullanıcı bir özellik sorarsa gerçek sistem durumuna göre cevap ver; uydurma vaat verme.
- POZİSYON KURALI: Açık pozisyon varken Moltbook'ta giriş fiyatı, SL, TP, lot veya yön PAYLAŞMA. Sadece genel piyasa yorumu yapabilirsin. Trade detayları (sembol, yön, giriş, SL/TP, sonuç) YALNIZCA pozisyon kapandıktan sonra özet/değerlendirme şeklinde paylaşılır.

ÜSLUP:
- Sade, samimi, teknik ama anlaşılır.
- Broker bakışı: veriye bak, mantığı sorgula, fırsatı gör.
- Post sonunda düşünce açan bir soru bırakabilirsin — ama zorla değil.
- Moltbook'ta cringe görünme: fazla süslü, tiyatral, kendini öven veya aşırı motivasyonel dil kullanma.
"""

def internette_arastir(sorgu):
    if not tavily: return "İnternet erişimi kapalı."
    key = sorgu.strip().lower()
    if key in LEARNED_MEMORY: return LEARNED_MEMORY[key]
    logger.info(f"🔍 Ajan internete dalıyor: {sorgu}")
    try:
        search_result = tavily_search_ekonomik(
            query=sorgu,
            max_results=3,
            cache_key=f"memory:{key}",
            ttl_min=180,
        )
        if not search_result:
            return "Arama atlandı (Tavily bütçe/limit/cache politikası)."
        context = ""
        for res in search_result.get('results', [])[:5]:
            context += f"\nKaynak: {res.get('url', '')}\nİçerik: {(res.get('content', '') or '')[:500]}\n"
        LEARNED_MEMORY[key] = context
        save_json(MEMORY_FILE, LEARNED_MEMORY)
        return context
    except Exception as e: return f"Arama hatası: {e}"

def ajana_sor(soru_tipi, gelen_yorum=None):
    karar_mesaji = [
        {"role": "system", "content": KARAKTER},
        {"role": "user", "content": f"Araştırayım mı? Sadece 'ARASTIR: [sorgu]' veya 'BILIYORUM' yaz. İçerik: {gelen_yorum if gelen_yorum else soru_tipi}"}
    ]
    karar = client.chat.completions.create(model="gpt-4o", messages=karar_mesaji).choices[0].message.content
    
    arastirma_notu = ""
    if "ARASTIR:" in karar:
        arastirma_notu = f"\n\nGüncel Veriler:\n{internette_arastir(karar.replace('ARASTIR:', '').strip())}"

    prompt = f"{KARAKTER}{arastirma_notu}\n\nGörev: {soru_tipi}"
    if soru_tipi == "Yorumu Cevapla" and gelen_yorum:
        uzunluk_profili = yorum_uzunlugu_profili(gelen_yorum)
        yorum_kurali = (
            "Buna 3-5 cümleyle, biraz daha derin ama sade bir yorum yaz."
            if uzunluk_profili == "derin"
            else "Buna en fazla 2 cümleyle kısa, doğal, sakin bir yorum yaz."
        )
        prompt += (
            f"\n\nİçerik: '{gelen_yorum}'. {yorum_kurali} "
            "Hitap cümlesi kurma, ukalalık yapma, çengel soru zorlaması yapma."
        )
    elif soru_tipi == "Moltbook Gözlem Özeti" and gelen_yorum:
        prompt += (
            "\n\nAşağıdaki Moltbook akış gözlemlerini sentezleyerek tek bir post üret. "
            "Maksimum 5 kısa madde halinde yaz. Finansal fırsat/risk dengesi ver. "
            "Kesinlikle selamlama, slogan, 'dijital meslektaşlarım', 'algoritmik dostlarım', 'Başlık:' kullanma. "
            "Gözlem dışı uydurma iddia yapma.\n\n"
            f"Gözlemler:\n{gelen_yorum}"
        )
    else:
        prompt += (
            "\n\nFinans/piyasalar/teknoloji üzerine kısa, sade, doğal bir post yaz. "
            "Selamlama cümlesi YAZMA, direkt konuya gir. Hype veya pazarlama dili kullanma. "
            "Aşırı iddialı slogan, teatral ifade ve kendini öven ton kullanma. "
            "ASLA şu ifadeleri kullanma: 'dijital meslektaşlarım', 'algoritmik dostlarım', 'Başlık:', 'Mesaj:'."
        )

    if soru_tipi == "Sohbet Et":
        prompt += f"\n\nGERÇEK SİSTEM DURUMU:\n{sistem_durum_ozeti()}"
        prompt += "\nKURAL: Bu durumun dışına çıkma, olmayan özellikleri varmış gibi anlatma. Gereksiz uzun açıklama yapma."

    response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "system", "content": prompt}]).choices[0].message.content
    return metin_temizle(response)

# --- MODÜLLER ---

def check_service_health():
    logger.info("Servis sağlığı kontrol ediliyor...")

    try:
        client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Sağlık kontrolü."}],
            max_tokens=1,
        )
        logger.info("OpenAI erişimi OK")
    except Exception as e:
        logger.error(f"OpenAI erişimi sorunlu: {e}")

    try:
        res = safe_request(
            "get",
            "https://www.moltbook.com/api/v1/posts",
            headers={"Authorization": f"Bearer {MOLTBOOK_API_KEY}"},
            params={"limit": 1},
            timeout=10,
        )
        if res.status_code == 200:
            logger.info("Moltbook API erişimi OK")
        else:
            logger.warning(f"Moltbook API yanıtı: {res.status_code} - {res.text[:200]}")
    except Exception as e:
        logger.error(f"Moltbook bağlantı sorunu: {e}")

    mt5_saglik_kontrolu()
    logger.info(
        f"Risk limitleri | mode={TRADE_EXECUTION_MODE} risk/trade={MAX_RISK_PER_TRADE_PCT}% "
        f"daily_max_loss={DAILY_MAX_LOSS_PCT}% max_open={MAX_OPEN_TRADES}"
    )


def record_post():
    POST_HISTORY.append(time.time())
    save_json(HISTORY_FILE, POST_HISTORY)


def rapor_mail_gonder(konu: str, govde: str):
    if not email_hazir_mi():
        logger.info("📭 E-posta ayarı eksik, rapor maili atlanıyor.")
        yerel_bildirim_gonder("Moltbook Raporu Hazır", "Mail ayarı eksik. Rapor dosyaya kaydedildi.")
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = konu
        msg["From"] = SMTP_FROM
        msg["To"] = RAPOR_EMAIL_TO
        msg.set_content(govde)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            if SMTP_USE_TLS:
                smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
        logger.info(f"📧 Rapor e-posta gönderildi: {RAPOR_EMAIL_TO}")
        return True
    except Exception as e:
        logger.warning(f"Rapor e-posta gönderilemedi: {e}")
        return False


def haftalik_slot_hazir_mi(now: datetime):
    try:
        saat, dakika = WEEKLY_HEALTH_TIME.split(":")
        hedef_dk = int(saat) * 60 + int(dakika)
    except Exception:
        hedef_dk = 21 * 60

    simdi_dk = now.hour * 60 + now.minute
    return now.weekday() == WEEKLY_HEALTH_DAY and simdi_dk >= hedef_dk


def haftalik_slot_id(now: datetime):
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}-{WEEKLY_HEALTH_DAY}@{WEEKLY_HEALTH_TIME}"


def trade_denemesi_slot_hazir_mi(now: datetime):
    try:
        saat, dakika = TRADE_DENEYIM_SLOT.split(":")
        hedef_dk = int(saat) * 60 + int(dakika)
    except Exception:
        hedef_dk = 23 * 60
    simdi_dk = now.hour * 60 + now.minute
    return simdi_dk >= hedef_dk


def trade_denemesi_slot_id(now: datetime):
    return f"{now.strftime('%Y-%m-%d')}@{TRADE_DENEYIM_SLOT}"


def trade_journal_yukle():
    data = load_json(TRADE_JOURNAL_FILE, [])
    if isinstance(data, list):
        return data[-20:]
    return []


def islem_denemesi_tecrube_metni_uret(girdiler):
    icerikler = []
    for kayit in girdiler:
        sembol = kayit.get("symbol", "?")
        yon = kayit.get("side", "?")
        sonuc = kayit.get("result", kayit.get("pnl", "?"))
        notu = (kayit.get("note") or "").replace("\n", " ")[:240]
        icerikler.append(f"- {sembol} | {yon} | sonuç={sonuc} | not={notu}")

    prompt = (
        "Aşağıdaki işlem günlüklerinden Moltbook için tek bir paylaşım yaz. "
        "Kişisel deneyim, his ve çıkarım aktar; rapor dili kullanma. "
        "Kısa, samimi, teknik ve dürüst ol. 'kesin kazanç' gibi iddialar yazma. "
        "2-5 kısa paragraf yeterli. Selamlama yok.\n\n"
        + "\n".join(icerikler)
    )
    yanit = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": KARAKTER},
            {"role": "user", "content": prompt},
        ],
    ).choices[0].message.content
    return metin_temizle(yanit)


def bugun_trade_kayitlarini_topla(now: datetime):
    bugun = now.strftime("%Y-%m-%d")
    queue_data = trade_queue_yukle()
    orders = queue_data.get("orders", [])
    gunluk = []
    for order in orders:
        zaman = (
            str(order.get("created_at") or "")
            or str(order.get("sent_at") or "")
            or str(order.get("filled_at") or "")
        )
        if not zaman.startswith(bugun):
            continue
        gunluk.append(order)
    return gunluk


def gunluk_trade_toplam_yorumu_uret(gunluk_orders, now: datetime):
    if not gunluk_orders:
        return ""

    durumlar = {"filled": 0, "closed": 0, "sent": 0, "failed": 0, "open": 0, "queued": 0, "approved": 0}
    yonler = {"buy": 0, "sell": 0}
    semboller = {}

    for o in gunluk_orders:
        st = str(o.get("status", "")).lower().strip()
        side = str(o.get("side", "")).lower().strip()
        sym = str(o.get("symbol", "")).upper().strip() or "?"
        if st in durumlar:
            durumlar[st] += 1
        if side in yonler:
            yonler[side] += 1
        if sym not in semboller:
            semboller[sym] = 0
        semboller[sym] += 1

    sembol_satirlari = [f"- {s}: {n}" for s, n in sorted(semboller.items(), key=lambda x: x[1], reverse=True)[:8]]
    ham = (
        f"Tarih: {now.strftime('%Y-%m-%d')}\n"
        f"Toplam işlem kaydı: {len(gunluk_orders)}\n"
        f"Durumlar: filled={durumlar['filled']}, closed={durumlar['closed']}, sent={durumlar['sent']}, "
        f"open={durumlar['open']}, failed={durumlar['failed']}, queued={durumlar['queued']}\n"
        f"Yön dağılımı: buy={yonler['buy']}, sell={yonler['sell']}\n"
        "Sembol dağılımı:\n"
        + "\n".join(sembol_satirlari)
    )

    prompt = (
        "Aşağıdaki günlük işlem toplamından Moltbook için TEK bir yorum yaz. "
        "Bu yorum pozisyon-bazlı değil, günün toplu sonucunu anlatmalı. "
        "Kısa, samimi, dürüst ve teknik olsun. "
        "Kesin kazanç/garanti iddiası yazma. Selamlama yok. 1-3 kısa paragraf.\n\n"
        f"{ham}"
    )
    yanit = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": KARAKTER},
            {"role": "user", "content": prompt},
        ],
        max_tokens=500,
    ).choices[0].message.content
    return metin_temizle(yanit)


def gunluk_trade_yorum_hedef_post_id(headers: dict):
    url = f"https://www.moltbook.com/api/v1/posts?submolt_name={SUBMOLT_NAME}&limit=30"
    res = safe_request("get", url, headers=headers)
    if res.status_code != 200:
        return None
    posts = res.json().get("posts", []) or []
    if not posts:
        return None

    for post in posts:
        pid = str(post.get("id") or "").strip()
        author = ((post.get("author") or {}).get("username") or "").strip().lower()
        if pid and author == "ovrthnk_agent":
            return pid
    for post in posts:
        pid = str(post.get("id") or "").strip()
        if pid:
            return pid
    return None


def trade_denemesi_tecrubesi_paylas():
    if not TRADE_DENEYIM_PAYLASIM_AKTIF:
        return

    now = datetime.now()
    if not trade_denemesi_slot_hazir_mi(now):
        return

    slot_id = trade_denemesi_slot_id(now)
    slots = RAPOR_DURUMU.get("trade_experience_slots", [])
    if slot_id in slots:
        return

    gunluk_orders = bugun_trade_kayitlarini_topla(now)
    if not gunluk_orders:
        logger.info("Bugün trade kaydı yok, günlük toplu yorum atlandı.")
        return

    yorum_ok, yorum_neden = yorum_yapabilir_mi()
    if not yorum_ok:
        logger.info(f"🛑 Günlük trade yorumu atlandı: {yorum_neden}")
        return

    yorum_text = gunluk_trade_toplam_yorumu_uret(gunluk_orders, now)
    ok, yorum_text, puan, nedenler = post_yayin_kontrolu(yorum_text, min_puan=85)
    if not ok:
        logger.info(f"⛔ Günlük trade yorumu atlanıyor (puan {puan}/100): {', '.join(nedenler) if nedenler else 'düşük kalite'}")
        return

    headers = {"Authorization": f"Bearer {MOLTBOOK_API_KEY}"}
    hedef_post_id = gunluk_trade_yorum_hedef_post_id(headers)
    if not hedef_post_id:
        logger.info("Günlük trade yorumu için hedef post bulunamadı, bu slot atlandı.")
        return

    comment_url = f"https://www.moltbook.com/api/v1/posts/{hedef_post_id}/comments"
    res = yorum_gonder_with_retry(comment_url, headers, yorum_text)

    if res.status_code in (200, 201):
        logger.info(f"💬 Günlük trade toplu yorumu paylaşıldı: post={hedef_post_id}")
        yorum_kota_kaydet()
        slots.append(slot_id)
        RAPOR_DURUMU["trade_experience_slots"] = slots[-120:]
        save_json(RAPOR_DURUM_DOSYASI, RAPOR_DURUMU)
    else:
        logger.warning(f"Günlük trade toplu yorumu başarısız: {res.status_code} - {res.text[:250]}")


# --- KAPALI POZİSYON ÖZET PAYLAŞIMI ---
TRADE_OZET_BEKLEME_SAAT = 1  # filled'dan bu kadar saat geçtikten sonra paylaş

def _kapali_islem_ozet_uret(order: dict) -> str:
    """GPT-4o ile kapanmış pozisyon değerlendirmesi üret."""
    sembol = order.get("symbol", "?")
    yon = order.get("side", "?")
    lot = order.get("lot", "?")
    sl = order.get("sl", "?")
    tp = order.get("tp", "?")
    kaynak = order.get("source", "")
    # ai_auto:neden formatından gerekçeyi çıkar
    neden = ""
    if kaynak.startswith("ai_auto:"):
        neden = kaynak[len("ai_auto:"):]
    ticket = order.get("ticket") or "-"
    filled_at = order.get("filled_at") or order.get("sent_at") or ""

    icerik = (
        f"Sembol: {sembol}\n"
        f"Yön: {yon}\n"
        f"Lot: {lot}\n"
        f"SL: {sl} | TP: {tp}\n"
        f"Ticket: {ticket}\n"
        f"Giriş zamanı: {filled_at}\n"
        f"AI gerekçesi: {neden if neden else 'manuel/test işlem'}\n"
    )
    prompt = (
        "Aşağıdaki işlemin kapandıktan sonraki Moltbook özet değerlendirmesini yaz.\n"
        "Şunları mutlaka kapsa:\n"
        "1. Bu işleme neden girildi (kısa, dürüst)\n"
        "2. Risk yönetimi (lot, SL/TP mantığı)\n"
        "3. Psikolojik etki: bu tür işlem nasıl bir his yaratır, traderın zihnine ne yapar?\n"
        "4. Öğrenilen ders (varsa)\n"
        "Kısa, samimi, kişisel yaz. Selamlama yok, reklam yok. "
        "SL/TP rakamlarını tekrar YAZMA — onlar geride kaldı. "
        "Analizini ve psikolojik değerlendirmeni öne çıkar.\n\n"
        f"{icerik}"
    )
    yanit = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": KARAKTER},
            {"role": "user", "content": prompt},
        ],
    ).choices[0].message.content
    return metin_temizle(yanit)


def kapali_islem_ozet_paylas():
    """Doldurulan (filled) emirleri için pozisyon kapandıktan sonra Moltbook özeti paylaş."""
    if not POST_PAYLASIM_AKTIF:
        return

    queue_data = trade_queue_yukle()
    orders = queue_data.get("orders", [])
    simdi = datetime.now()
    degisti = False

    for order in orders:
        if order.get("status") not in {"filled", "closed"}:
            continue
        if order.get("shared_at"):
            continue  # zaten paylaşıldı

        # filled/sent_at zamanı kontrolü — en az TRADE_OZET_BEKLEME_SAAT kadar geçmeli
        zaman_str = order.get("filled_at") or order.get("sent_at") or ""
        if zaman_str:
            try:
                zaman = datetime.fromisoformat(zaman_str)
                fark_saat = (simdi - zaman).total_seconds() / 3600
                if fark_saat < TRADE_OZET_BEKLEME_SAAT:
                    continue  # henüz erken, bekle
            except Exception:
                pass  # zaman parse edemedik, yine de devam et

        if not can_post():
            logger.info("Günlük post limiti dolu, kapanış özeti atlandı.")
            return

        try:
            post_text = _kapali_islem_ozet_uret(order)
        except Exception as e:
            logger.warning(f"Kapanış özeti üretilemedi ({order.get('id')}): {e}")
            continue

        ok, post_text, puan, nedenler = post_yayin_kontrolu(post_text, min_puan=90)
        if not ok:
            logger.info(f"⛔ Kapanış özeti atlanıyor (puan {puan}/100, id={order.get('id')}): {', '.join(nedenler or [])}")
            order["shared_at"] = f"SKIP:{simdi.isoformat(timespec='seconds')}"
            degisti = True
            continue

        title = post_text.strip().split("\n")[0][:80] or f"{order.get('symbol', '?')} İşlem Özeti"
        url = "https://www.moltbook.com/api/v1/posts"
        headers = {"Authorization": f"Bearer {MOLTBOOK_API_KEY}", "Content-Type": "application/json"}
        body = {"submolt_name": SUBMOLT_NAME, "title": title, "content": post_text}
        res = safe_request("post", url, json=body, headers=headers)

        if res.status_code in (200, 201):
            order["shared_at"] = simdi.isoformat(timespec="seconds")
            logger.info(f"📊 Kapanış özeti paylaşıldı: {order.get('symbol')} {order.get('side')} → {title}")
            record_post()
            degisti = True
        else:
            logger.warning(f"Kapanış özeti gönderilemedi ({order.get('id')}): {res.status_code} - {res.text[:200]}")

    if degisti:
        trade_queue_kaydet(queue_data)


def haftalik_saglik_raporu_uret_ve_gonder(slot_id: str):
    logger.info(f"🧭 Haftalık sağlık raporu hazırlanıyor ({slot_id})...")
    url = f"https://www.moltbook.com/api/v1/posts?submolt_name={SUBMOLT_NAME}&limit=40"
    headers = {"Authorization": f"Bearer {MOLTBOOK_API_KEY}"}
    res = safe_request("get", url, headers=headers)
    if res.status_code != 200:
        logger.warning(f"Haftalık rapor için postlar çekilemedi: {res.status_code}")
        return False

    posts = res.json().get("posts", [])
    if not posts:
        rapor = (
            f"🧭 Haftalık Sağlık Raporu ({slot_id})\n\n"
            "Bu hafta yeterli veri bulunamadı."
        )
    else:
        kisa_akıs = []
        for post in posts[:30]:
            author = post.get("author", {}).get("username") or "bilinmiyor"
            title = post.get("title", "Başlıksız")
            content = (post.get("content", "") or "").replace("\n", " ")[:220]
            kisa_akıs.append(f"- @{author} | {title} | {content}")

        toplam_post = len(posts)
        benzersiz_yazar = len({(p.get("author", {}) or {}).get("username") for p in posts if (p.get("author", {}) or {}).get("username")})

        analiz_prompt = (
            "Aşağıdaki Moltbook akışından haftalık sağlık raporu çıkar. "
            "Kısa ve net yaz. Klinik teşhis YAPMA. 'Psikolojik Durum' bölümünü sadece ekosistem ruh hali olarak değerlendir. "
            "Şu başlıklar zorunlu: 'Genel Sağlık', 'Riskler', 'Fırsatlar', 'Psikolojik Durum (Ekosistem Ruh Hali, Klinik Değil)', 'Önerilen Aksiyonlar'. "
            "Her başlık altında en fazla 5 madde yaz. Uydurma bilgi yazma.\n\n"
            + "\n".join(kisa_akıs)
        )
        analiz = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": KARAKTER},
                {"role": "user", "content": analiz_prompt},
            ],
        ).choices[0].message.content.strip()

        rapor = (
            f"🧭 Haftalık Sağlık Raporu ({slot_id})\n\n"
            f"- İncelenen post: {toplam_post}\n"
            f"- Benzersiz yazar: {benzersiz_yazar}\n\n"
            f"{analiz}\n"
        )

    haftalik_file = os.path.join(os.path.dirname(__file__), "haftalik_saglik_raporu.txt")
    with open(haftalik_file, "w", encoding="utf-8") as f:
        f.write(rapor)
    logger.info(f"🩺 Haftalık rapor güncellendi: {haftalik_file}")

    os.makedirs(RAPOR_ARSIV_KLASORU, exist_ok=True)
    arsiv_adi = f"haftalik_{slot_id.replace(':', '-').replace(' ', '_')}.txt"
    arsiv_yolu = os.path.join(RAPOR_ARSIV_KLASORU, arsiv_adi)
    with open(arsiv_yolu, "w", encoding="utf-8") as f:
        f.write(rapor)
    logger.info(f"🗂️ Haftalık rapor arşive kaydedildi: {arsiv_yolu}")

    rapor_mail_gonder(f"Haftalık Sağlık Raporu - {slot_id}", rapor)
    return True


def haftalik_saglik_raporu_kontrolu_ve_gonderimi():
    now = datetime.now()
    if not haftalik_slot_hazir_mi(now):
        return

    slot_id = haftalik_slot_id(now)
    weekly_slots = RAPOR_DURUMU.get("weekly_slots", [])
    if slot_id in weekly_slots:
        return

    basarili = haftalik_saglik_raporu_uret_ve_gonder(slot_id)
    if not basarili:
        return

    weekly_slots.append(slot_id)
    RAPOR_DURUMU["weekly_slots"] = weekly_slots[-60:]
    save_json(RAPOR_DURUM_DOSYASI, RAPOR_DURUMU)
    logger.info(f"✅ Haftalık sağlık raporu tamamlandı: {slot_id}")


def firsatlari_ara_ve_rapor_et(slot_id: str):
    logger.info(f"🔍 Zamanlı rapor hazırlanıyor ({slot_id})...")
    url = "https://www.moltbook.com/api/v1/posts?limit=30"
    headers = {"Authorization": f"Bearer {MOLTBOOK_API_KEY}"}
    res = safe_request("get", url, headers=headers)
    if res.status_code != 200:
        logger.warning(f"Postlar çekilemedi: {res.status_code}")
        return False

    posts = res.json().get("posts", [])
    post_ozetleri = []
    for post in posts[:20]:
        baslik = post.get("title", "Başlıksız")
        icerik = (post.get("content", "") or "").replace("\n", " ")[:500]
        author = post.get("author", {}).get("username") or "bilinmiyor"
        post_ozetleri.append(f"- @{author} | {baslik} | {icerik}")

    if not post_ozetleri:
        rapor = f"📊 Moltbook Raporu ({slot_id})\n\nİncelenecek post bulunamadı."
    else:
        rapor_prompt = (
            "Aşağıdaki Moltbook akışını incele ve sadece Türkçe rapor yaz. "
            "Şu başlıklar mutlaka olsun: 'Fırsatlar', 'Yeni Gelişmeler', 'İşe Yarayabilecek Notlar'. "
            "Her başlık altında en fazla 5 kısa madde yaz. Uydurma bilgi yazma, sadece verilen içeriklerden çıkarım yap.\n\n"
            + "\n".join(post_ozetleri)
        )
        rapor_icerik = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": KARAKTER},
                {"role": "user", "content": rapor_prompt},
            ],
        ).choices[0].message.content.strip()
        rapor = f"📊 Moltbook Raporu ({slot_id})\n\n{rapor_icerik}\n"

    rapor_file = os.path.join(os.path.dirname(__file__), "gunluk_rapor.txt")
    with open(rapor_file, "w", encoding="utf-8") as f:
        f.write(rapor)
    logger.info(f"📄 Rapor güncellendi: {rapor_file}")

    os.makedirs(RAPOR_ARSIV_KLASORU, exist_ok=True)
    arsiv_adi = slot_id.replace(":", "-").replace(" ", "_") + ".txt"
    arsiv_yolu = os.path.join(RAPOR_ARSIV_KLASORU, arsiv_adi)
    with open(arsiv_yolu, "w", encoding="utf-8") as f:
        f.write(rapor)
    logger.info(f"🗂️ Rapor arşive kaydedildi: {arsiv_yolu}")

    rapor_mail_gonder(f"Moltbook Raporu - {slot_id}", rapor)
    return True


def zamanli_rapor_kontrolu_ve_gonderimi():
    now = datetime.now()
    slot = rapor_slotu_bul(now)
    if not slot:
        return

    slot_id = f"{now.strftime('%Y-%m-%d')} {slot}"
    sent_slots = RAPOR_DURUMU.get("sent_slots", [])
    if slot_id in sent_slots:
        return

    basarili = firsatlari_ara_ve_rapor_et(slot_id)
    if not basarili:
        return

    sent_slots.append(slot_id)
    RAPOR_DURUMU["sent_slots"] = sent_slots[-120:]
    save_json(RAPOR_DURUM_DOSYASI, RAPOR_DURUMU)
    logger.info(f"🕒 Rapor slotu tamamlandı: {slot_id}")


def _safe_math_eval(expr: str):
    izinli = {
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult,
        ast.Div, ast.USub, ast.UAdd, ast.Constant, ast.Load,
    }
    node = ast.parse(expr, mode="eval")
    for child in ast.walk(node):
        if type(child) not in izinli:
            raise ValueError("unsupported expression")
    return eval(compile(node, "<math>", "eval"), {"__builtins__": {}}, {})


def matematik_sorusu_coz(challenge: str):
    metin = (challenge or "").strip()
    if not metin:
        return None

    expr = metin.replace("×", "*").replace("x", "*").replace("X", "*").replace("÷", "/")
    expr = expr.replace(",", ".")
    expr = re.sub(r"[^0-9\+\-\*\/\(\)\.]", " ", expr)
    expr = re.sub(r"\s+", "", expr)
    if not expr:
        return None

    try:
        sonuc = float(_safe_math_eval(expr))
        return f"{sonuc:.2f}"
    except Exception:
        return None


def yorum_gecmisi_var_mi(post_id: str):
    return post_id in set(MOLTBOOK_COMMENT_HISTORY.get("commented_post_ids", []))


def yorum_gecmisi_kaydet(post_id: str):
    ids = MOLTBOOK_COMMENT_HISTORY.get("commented_post_ids", [])
    if post_id in ids:
        return
    MOLTBOOK_COMMENT_HISTORY["commented_post_ids"] = (ids + [post_id])[-5000:]
    save_json(MOLTBOOK_COMMENT_HISTORY_FILE, MOLTBOOK_COMMENT_HISTORY)


def yorum_kota_bakimi():
    now = time.time()
    stamps = [float(ts) for ts in MOLTBOOK_COMMENT_HISTORY.get("comment_timestamps", []) if now - float(ts) <= 86400]
    MOLTBOOK_COMMENT_HISTORY["comment_timestamps"] = stamps
    if float(MOLTBOOK_COMMENT_HISTORY.get("pause_until_ts", 0)) < now:
        MOLTBOOK_COMMENT_HISTORY["pause_until_ts"] = 0
    save_json(MOLTBOOK_COMMENT_HISTORY_FILE, MOLTBOOK_COMMENT_HISTORY)


def son_bir_saat_yorum_sayisi():
    now = time.time()
    return len([ts for ts in MOLTBOOK_COMMENT_HISTORY.get("comment_timestamps", []) if now - float(ts) <= 3600])


def yorum_yapabilir_mi():
    yorum_kota_bakimi()
    now = time.time()
    pause_until = float(MOLTBOOK_COMMENT_HISTORY.get("pause_until_ts", 0))
    if pause_until > now:
        return False, f"server cooldown aktif ({int((pause_until - now) // 60)} dk kaldı)"
    saatlik = son_bir_saat_yorum_sayisi()
    if saatlik >= MAX_COMMENTS_PER_HOUR:
        return False, f"yerel saatlik yorum limiti dolu ({saatlik}/{MAX_COMMENTS_PER_HOUR})"
    return True, "ok"


def yorum_kota_kaydet():
    stamps = MOLTBOOK_COMMENT_HISTORY.get("comment_timestamps", [])
    stamps.append(time.time())
    MOLTBOOK_COMMENT_HISTORY["comment_timestamps"] = stamps[-1000:]
    save_json(MOLTBOOK_COMMENT_HISTORY_FILE, MOLTBOOK_COMMENT_HISTORY)


def yorum_cooldown_uygula(seconds: int):
    MOLTBOOK_COMMENT_HISTORY["pause_until_ts"] = max(float(MOLTBOOK_COMMENT_HISTORY.get("pause_until_ts", 0)), time.time() + max(60, seconds))
    save_json(MOLTBOOK_COMMENT_HISTORY_FILE, MOLTBOOK_COMMENT_HISTORY)


def yorum_dogrula(verification: dict, headers: dict):
    """Moltbook'un yorum sonrası gönderdiği matematik doğrulama sorusunu çöz ve gönder."""
    try:
        code = verification.get("verification_code")
        challenge = verification.get("challenge_text", "")
        if not code or not challenge:
            return
        cevap = matematik_sorusu_coz(challenge)
        if not cevap:
            cevap = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Matematik problemini çöz. SADECE sayıyı yaz, 2 ondalık basamakla. (örnek: '46.00')"},
                    {"role": "user", "content": challenge},
                ],
                max_tokens=20,
            ).choices[0].message.content.strip()
        res = safe_request(
            "post",
            "https://www.moltbook.com/api/v1/verify",
            json={"verification_code": code, "answer": cevap},
            headers=headers,
        )
        if res.status_code in (200, 201):
            logger.info(f"✅ Yorum doğrulandı (cevap: {cevap})")
        else:
            logger.warning(f"Yorum doğrulama başarısız: {res.status_code} {res.text[:200]}")
    except Exception as e:
        logger.warning(f"Yorum doğrulama hatası: {e}")


def moltbook_gozlem_kaydet(post: dict):
    try:
        post_id = str(post.get("id") or "").strip()
        if not post_id:
            return

        seen = MOLTBOOK_INSIGHTS.get("seen_post_ids", [])
        if post_id in seen:
            return

        author = post.get("author", {}).get("username") or "bilinmiyor"
        title = (post.get("title") or "").strip()
        content = (post.get("content") or "").replace("\n", " ").strip()
        merged = f"{title} {content}".strip()

        item = {
            "id": post_id,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "author": author,
            "text": merged[:700],
        }

        items = MOLTBOOK_INSIGHTS.get("items", [])
        items.append(item)
        MOLTBOOK_INSIGHTS["items"] = items[-MOLTBOOK_INSIGHT_MAX_ITEMS:]
        MOLTBOOK_INSIGHTS["seen_post_ids"] = (seen + [post_id])[-5000:]
        save_json(MOLTBOOK_INSIGHT_FILE, MOLTBOOK_INSIGHTS)
    except Exception as e:
        logger.warning(f"Moltbook gözlem kaydı hatası: {e}")


def moltbook_gozlem_ozet_kaynagi(limit: int = 50):
    items = MOLTBOOK_INSIGHTS.get("items", [])
    if len(items) < limit:
        return None

    secilen = items[-limit:]
    satirlar = []
    for row in secilen:
        satirlar.append(f"- @{row.get('author', 'bilinmiyor')}: {(row.get('text') or '')[:280]}")
    return "\n".join(satirlar)


def diger_postlari_tara_ve_etkiles():
    logger.info("🤝 Diğer postları tarayıp etkileşime giriyorum...")
    yorum_ok, yorum_neden = yorum_yapabilir_mi()
    if not yorum_ok:
        logger.info(f"🛑 Yorum turu atlandı: {yorum_neden}")
        return

    url = f"https://www.moltbook.com/api/v1/posts?submolt_name={SUBMOLT_NAME}&limit=20"
    headers = {"Authorization": f"Bearer {MOLTBOOK_API_KEY}"}
    res = safe_request("get", url, headers=headers)
    if res.status_code != 200:
        logger.warning(f"Postlar çekilemedi: {res.status_code}")
        return

    posts = res.json().get("posts", [])
    yeni_gozlem = 0
    basarili_yorum = 0
    for post in posts:
        post_id = str(post.get("id") or "").strip()
        if post.get("author", {}).get("username") == "ovrthnk_agent":
            continue
        if not post_id:
            continue
        if yorum_gecmisi_var_mi(post_id):
            continue

        onceki = len(MOLTBOOK_INSIGHTS.get("items", []))
        moltbook_gozlem_kaydet(post)
        if len(MOLTBOOK_INSIGHTS.get("items", [])) > onceki:
            yeni_gozlem += 1

        yorum_kaynagi = post.get("content", "")[:600]
        cevap, puan, nedenler = uygun_icerik_uret("Yorumu Cevapla", gelen_yorum=yorum_kaynagi)
        if puan < 75:
            logger.info(f"⛔ Yorum atlanıyor (uygunluk puanı {puan}/100): {', '.join(nedenler) if nedenler else 'düşük kalite'}")
            continue
        comment_url = f"https://www.moltbook.com/api/v1/posts/{post_id}/comments"
        yorum_res = yorum_gonder_with_retry(comment_url, headers, cevap)
        if yorum_res.status_code in (200, 201):
            logger.info(f"💬 Yorum bırakıldı: {post_id} (puan {puan}/100)")
            yorum_gecmisi_kaydet(post_id)
            yorum_kota_kaydet()
            basarili_yorum += 1
            data = yorum_res.json()
            verification = data.get("comment", {}).get("verification") or data.get("verification")
            if verification:
                yorum_dogrula(verification, headers)
        else:
            logger.warning(f"Yorum başarısız: {yorum_res.status_code} {yorum_res.text[:200]}")
            if yorum_res.status_code == 429:
                try:
                    body = yorum_res.json()
                except Exception:
                    body = {}
                retry_after = int(body.get("retry_after_seconds") or 3600)
                yorum_cooldown_uygula(retry_after)
                logger.info(f"🛑 Moltbook yorum cooldown aktif: {retry_after} sn")
                break
        if basarili_yorum >= MAX_COMMENTS_PER_TUR:
            logger.info(f"🧩 Bu tur yorum kotası doldu ({MAX_COMMENTS_PER_TUR} yorum).")
            break
        time.sleep(5)

    logger.info(
        f"📚 Moltbook gözlem havuzu: {len(MOLTBOOK_INSIGHTS.get('items', []))} kayıt "
        f"(+{yeni_gozlem} yeni, post için hedef {MOLTBOOK_INSIGHT_MIN_POST})"
    )


def paylas_ve_takil():
    if not POST_PAYLASIM_AKTIF:
        return

    now_dt = datetime.now()
    aktif_slot = post_slotu_bul(now_dt)
    if not aktif_slot:
        logger.info(f"🛡️ Post beklemede. Sonraki post slotu: {sonraki_post_saati(now_dt)}")
        return

    slot_id = f"{now_dt.strftime('%Y-%m-%d')} {aktif_slot}"
    post_slots = RAPOR_DURUMU.get("post_slots", [])
    if slot_id in post_slots:
        logger.info(f"🛡️ Bu post slotu zaten tamamlandı: {slot_id}")
        return

    if not can_post():
        logger.info("Günlük post limiti doldu.")
        return

    gozlem_kaynagi = moltbook_gozlem_ozet_kaynagi(MOLTBOOK_INSIGHT_MIN_POST)
    if not gozlem_kaynagi:
        mevcut = len(MOLTBOOK_INSIGHTS.get("items", []))
        logger.info(
            f"🧠 Özet post beklemede: gözlem {mevcut}/{MOLTBOOK_INSIGHT_MIN_POST}. "
            "Yeterli veri birikmeden yeni post atılmıyor."
        )
        return

    logger.info("🕒 Post zamanı geldi, içerik hazırlanıyor...")
    yeni_post, puan, nedenler = uygun_icerik_uret("Moltbook Gözlem Özeti", gelen_yorum=gozlem_kaynagi)
    if puan < 88:
        logger.info(f"⛔ Post atlanıyor (uygunluk puanı {puan}/100): {', '.join(nedenler) if nedenler else 'düşük kalite'}")
        return
    title = yeni_post.strip().split("\n")[0][:80] or "Piyasa Notu"

    url = "https://www.moltbook.com/api/v1/posts"
    headers = {"Authorization": f"Bearer {MOLTBOOK_API_KEY}", "Content-Type": "application/json"}
    body = {"submolt_name": SUBMOLT_NAME, "title": title, "content": yeni_post}
    res = safe_request("post", url, json=body, headers=headers)

    if res.status_code in (200, 201):
        logger.info(f"✅ Yeni post atıldı: {title} (puan {puan}/100)")
        record_post()
        post_slots.append(slot_id)
        RAPOR_DURUMU["post_slots"] = post_slots[-120:]
        save_json(RAPOR_DURUM_DOSYASI, RAPOR_DURUMU)
    else:
        logger.warning(f"Post atılamadı: {res.status_code} - {res.text[:300]}")
        if res.status_code == 429:
            try:
                retry_after = res.json().get("retry_after_seconds", 150)
            except Exception:
                retry_after = 150
            logger.info(f"Rate limit: {retry_after} saniye bekleniyor.")
            time.sleep(retry_after)


def kilit_al():
    if os.path.exists(KILIT_DOSYASI):
        try:
            with open(KILIT_DOSYASI, "r", encoding="utf-8") as f:
                eski_pid = int(f.read().strip())
            os.kill(eski_pid, 0)
            logger.warning(f"Ajan zaten çalışıyor (pid={eski_pid}).")
            return False
        except Exception:
            try:
                os.remove(KILIT_DOSYASI)
            except Exception:
                pass

    with open(KILIT_DOSYASI, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    return True


def kilidi_birak():
    try:
        if os.path.exists(KILIT_DOSYASI):
            os.remove(KILIT_DOSYASI)
    except Exception:
        pass



# ─── OTONOM TRADE SİSTEMİ ──────────────────────────────────────────────────

def mt5_account_state_file():
    return os.path.join(MT5_FILE_BRIDGE_DIR, "ovrthnk_account_state.csv")


def mt5_symbol_info_file():
    return os.path.join(MT5_FILE_BRIDGE_DIR, "ovrthnk_symbol_info.csv")


def mt5_symbol_request_file():
    return os.path.join(MT5_FILE_BRIDGE_DIR, "ovrthnk_symbol_request.txt")


def gunluk_durum_yukle() -> dict:
    bugun = datetime.now().strftime("%Y-%m-%d")
    data = load_json(GUNLUK_DURUM_DOSYASI, {})
    if data.get("tarih") != bugun:
        return {"tarih": bugun, "baslangic_bakiye": None, "acilan_islem_sayisi": 0}
    return data


def gunluk_durum_kaydet(durum: dict):
    save_json(GUNLUK_DURUM_DOSYASI, durum)


def piyasa_acik_mi() -> bool:
    """Forex/CFD piyasasının şu an açık olduğunu kontrol et.
    Piyasa kabaca Pzt 00:00 UTC – Cum 22:00 UTC arası açıktır.
    Gece yarısı ve hafta sonu işlem denememek için kullanılır.
    """
    now_utc = datetime.utcnow()
    weekday = now_utc.weekday()   # 0=Pzt ... 6=Paz
    hour_utc = now_utc.hour
    minute_utc = now_utc.minute
    # Pazar günü tüm gün kapalı
    if weekday == 6:
        return False
    # Cumartesi günü tüm gün kapalı
    if weekday == 5:
        return False
    # Cuma 22:00 UTC'den sonra kapalı
    if weekday == 4 and (hour_utc * 60 + minute_utc) >= 22 * 60:
        return False
    # Pazartesi 00:00 UTC'den önce kapalı (çok nadir ama koruma)
    # Gece 23:00-23:59 UTC arası likidite düşük, işlem yapma
    if hour_utc == 23:
        return False
    return True


def bugun_gercek_acilan_islem_sayisi() -> int:
    """Bugün açılan ve failed/cancelled/rejected OLMAYAN ai_auto emirlerini say.
    Bu, gece piyasa kapalıyken denemeler sayacı patlatmasını önler.
    """
    bugun = datetime.now().strftime("%Y-%m-%d")
    queue_data = trade_queue_yukle()
    return len([
        o for o in queue_data.get("orders", [])
        if o.get("created_at", "").startswith(bugun)
        and o.get("source", "").startswith("ai_auto")
        and o.get("status") not in {"failed", "cancelled", "rejected"}
    ])


def mt5_dosya_hesap_ozeti() -> dict | None:
    """EA'nın yazdığı account_state.csv dosyasından hesap bilgisi oku."""
    state_path = mt5_account_state_file()
    if not os.path.exists(state_path):
        return None
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if rows:
            r = rows[-1]
            open_pos_raw = r.get("open_positions")
            return {
                "balance": float(r.get("balance") or 0),
                "equity": float(r.get("equity") or 0),
                "profit": float(r.get("profit") or 0),
                "margin_free": float(r.get("margin_free") or 0),
                "open_positions": int(float(open_pos_raw)) if open_pos_raw is not None else None,
            }
    except Exception as e:
        logger.warning(f"Hesap durum dosyası okunamadı: {e}")
    return None


def sembol_bilgisi_al(symbol: str) -> dict | None:
    """EA'dan sembol bilgisi iste ve oku (file-bridge üzerinden).
    Spread, contract size, lot sınırları ve güncel bid/ask fiyatını döndürür.
    EA yanıt vermezse None döner ve işlem açılmaz.
    """
    req_path = mt5_symbol_request_file()
    info_path = mt5_symbol_info_file()
    try:
        if os.path.exists(info_path):
            os.remove(info_path)
        os.makedirs(MT5_FILE_BRIDGE_DIR, exist_ok=True)
        with open(req_path, "w", encoding="utf-8") as f:
            f.write(symbol.upper().strip())
        for _ in range(15):
            time.sleep(0.7)
            if not os.path.exists(info_path):
                continue
            with open(info_path, "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if rows and rows[0].get("symbol", "").upper() == symbol.upper():
                r = rows[0]
                return {
                    "symbol": r.get("symbol"),
                    "spread": float(r.get("spread") or 0),
                    "contract_size": float(r.get("contract_size") or 100000),
                    "min_lot": float(r.get("min_lot") or 0.01),
                    "max_lot": float(r.get("max_lot") or 100),
                    "lot_step": float(r.get("lot_step") or 0.01),
                    "digits": int(float(r.get("digits") or 5)),
                    "tick_value": float(r.get("tick_value") or 0),
                    "tick_size": float(r.get("tick_size") or 0.00001),
                    "bid": float(r.get("bid") or 0),
                    "ask": float(r.get("ask") or 0),
                }
    except Exception as e:
        logger.warning(f"Sembol bilgisi alınamadı ({symbol}): {e}")
    return None


def lot_hesapla(balance: float, risk_pct: float, sl_price_dist: float,
                tick_value: float, tick_size: float,
                lot_step: float, min_lot: float, max_lot: float) -> float:
    """Risk yüzdesi ve SL mesafesine göre lot büyüklüğü hesapla."""
    if tick_value <= 0 or tick_size <= 0 or sl_price_dist <= 0:
        return min_lot
    risk_amount = balance * (risk_pct / 100.0)
    sl_ticks = sl_price_dist / tick_size
    lot = risk_amount / (sl_ticks * tick_value)
    lot = round(round(lot / lot_step) * lot_step, 8)
    return min(max_lot, max(min_lot, lot))


def trade_zekasi_yukle() -> dict:
    varsayilan = {
        "son_guncelleme": "",
        "toplam_filled": 0,
        "sembol_istatistik": {},
        "yon_istatistik": {"buy": 0, "sell": 0},
        "son_kararlar": [],
        "dersler": "",
        "uyarilar": [],
        "kullanici_stili": {
            "profil_url": TRADINGVIEW_PROFILE_URL,
            "ozet": "",
            "son_guncelleme": "",
        },
    }
    data = load_json(TRADE_INTELLIGENCE_FILE, varsayilan)
    if not isinstance(data, dict):
        return varsayilan
    for k, v in varsayilan.items():
        if k not in data:
            data[k] = v
    if not isinstance(data.get("sembol_istatistik"), dict):
        data["sembol_istatistik"] = {}
    if not isinstance(data.get("yon_istatistik"), dict):
        data["yon_istatistik"] = {"buy": 0, "sell": 0}
    if not isinstance(data.get("son_kararlar"), list):
        data["son_kararlar"] = []
    if not isinstance(data.get("uyarilar"), list):
        data["uyarilar"] = []
    if not isinstance(data.get("kullanici_stili"), dict):
        data["kullanici_stili"] = varsayilan["kullanici_stili"]
    return data


def tradingview_stil_ozeti_uret() -> str:
    if not TRADINGVIEW_PROFILE_URL:
        return ""
    parcalar = []
    try:
        res = requests.get(TRADINGVIEW_PROFILE_URL, timeout=20)
        if res.status_code == 200:
            html = res.text or ""
            title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            desc_m = re.search(
                r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
                html,
                re.IGNORECASE | re.DOTALL,
            )
            if title_m:
                parcalar.append(re.sub(r"\s+", " ", title_m.group(1)).strip())
            if desc_m:
                parcalar.append(re.sub(r"\s+", " ", desc_m.group(1)).strip())
    except Exception as e:
        logger.warning(f"TradingView profil okuma hatası: {e}")

    if tavily:
        try:
            q = f"{TRADINGVIEW_PROFILE_URL} tradingview ideas analysis style"
            tv_res = tavily_search_ekonomik(
                query=q,
                max_results=3,
                cache_key=f"tv_style:{TRADINGVIEW_PROFILE_URL.lower()}",
                ttl_min=max(60, TAVILY_STYLE_CACHE_HOURS * 60),
            )
            if not tv_res:
                tv_res = {}
            if tv_res.get("answer"):
                parcalar.append(tv_res.get("answer", ""))
            for r in tv_res.get("results", [])[:3]:
                icerik = (r.get("content") or "").strip()
                if icerik:
                    parcalar.append(icerik[:400])
        except Exception as e:
            logger.warning(f"TradingView Tavily arama hatası: {e}")

    ham_ozet = "\n".join([p for p in parcalar if p]).strip()
    if not ham_ozet:
        return ""

    try:
        style_prompt = f"""Aşağıdaki metinler bir traderın TradingView profilinden/toplanan içeriklerden geldi.
Kısa bir "analiz stili özeti" üret:
- Zamanlama yaklaşımı
- Teknik/temel odak
- Risk yönetimi yaklaşımı
- Çift yönlü piyasa bakışı (buy/sell)

Maksimum 6 kısa madde, Türkçe, sade:

{ham_ozet[:6000]}"""
        yanit = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Kısa ve somut çıkarım yapan bir trading analiz asistanısın."},
                {"role": "user", "content": style_prompt},
            ],
            max_tokens=500,
        ).choices[0].message.content.strip()
        return yanit[:2000]
    except Exception as e:
        logger.warning(f"TradingView stil özeti üretilemedi: {e}")
        return ham_ozet[:1200]


def trade_zekasi_guncelle():
    zeka = trade_zekasi_yukle()
    queue_data = trade_queue_yukle()
    orders = queue_data.get("orders", [])
    if not isinstance(orders, list):
        orders = []

    filled = [o for o in orders if o.get("status") == "filled"]
    sembol_istatistik = {}
    yon_buy = 0
    yon_sell = 0

    for o in filled:
        sym = str(o.get("symbol", "")).upper().strip()
        side = str(o.get("side", "")).lower().strip()
        if not sym:
            continue
        if sym not in sembol_istatistik:
            sembol_istatistik[sym] = {"filled": 0, "buy": 0, "sell": 0}
        sembol_istatistik[sym]["filled"] += 1
        if side in {"buy", "sell"}:
            sembol_istatistik[sym][side] += 1
            if side == "buy":
                yon_buy += 1
            else:
                yon_sell += 1

    son_kararlar = []
    for o in orders[-30:]:
        son_kararlar.append({
            "tarih": o.get("created_at") or o.get("updated_at") or "",
            "symbol": str(o.get("symbol", "")).upper().strip(),
            "side": str(o.get("side", "")).lower().strip(),
            "neden": str(o.get("source", ""))[:80],
            "sonuc": str(o.get("status", "")),
        })

    tv_ozet = tradingview_stil_ozeti_uret()
    if tv_ozet:
        zeka["kullanici_stili"] = {
            "profil_url": TRADINGVIEW_PROFILE_URL,
            "ozet": tv_ozet,
            "son_guncelleme": datetime.now().isoformat(),
        }

    zeka["son_guncelleme"] = datetime.now().isoformat()
    zeka["toplam_filled"] = len(filled)
    zeka["sembol_istatistik"] = sembol_istatistik
    zeka["yon_istatistik"] = {"buy": yon_buy, "sell": yon_sell}
    zeka["son_kararlar"] = son_kararlar[-20:]

    buy_sell_mesaji = (
        f"Buy/Sell dağılımı: buy={yon_buy}, sell={yon_sell}. "
        "Forex çift yönlüdür; sadece buy odaklı kalma."
    )
    sembol_mesaji = ""
    if sembol_istatistik:
        en_cok = sorted(sembol_istatistik.items(), key=lambda x: x[1].get("filled", 0), reverse=True)[0][0]
        sembol_mesaji = (
            f"Ağırlık verilen sembol: {en_cok}. "
            "Tek sembole kilitlenme; fırsata göre EURUSD/GBPUSD/USDJPY/XAUUSD arasında seç."
        )

    try:
        ders_prompt = f"""Aşağıdaki trade geçmişinden kısa ders çıkar.
Hedef:
1) Tek yön (sadece buy) veya tek sembol (sadece XAUUSD) sapmasını azalt
2) Çift yönlü piyasa mantığını koru
3) Kullanıcının TradingView stilinden öğren, ama ona kilitlenme

İstatistik:
{json.dumps(zeka.get('sembol_istatistik', {}), ensure_ascii=False)}
Yön:
{json.dumps(zeka.get('yon_istatistik', {}), ensure_ascii=False)}
Kullanıcı stili:
{(zeka.get('kullanici_stili', {}) or {}).get('ozet', '')}
Önceki dersler:
{zeka.get('dersler', '')}

Çıktı formatı:
- 4-6 kısa ders maddesi
- 2-4 kısa uyarı maddesi"""
        ders_yanit = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Kısa, uygulanabilir ve risk odaklı trade koçu gibi yaz."},
                {"role": "user", "content": ders_prompt},
            ],
            max_tokens=700,
        ).choices[0].message.content.strip()
        zeka["dersler"] = ders_yanit[:2500]
        zeka["uyarilar"] = [buy_sell_mesaji, sembol_mesaji] if sembol_mesaji else [buy_sell_mesaji]
    except Exception as e:
        logger.warning(f"Trade zekası ders üretimi başarısız: {e}")
        zeka["dersler"] = "\n".join([
            "- Forex çift yönlüdür: buy kadar sell fırsatları da değerlidir.",
            "- İlk işlem buy oldu diye sonraki işlemleri aynı yöne sabitleme.",
            "- XAUUSD güçlü olsa da tek sembole kilitlenmeden fırsat bazlı hareket et.",
            "- Kullanıcı stilini referans al ama kör kopyalama yapma; piyasa koşuluna adaptif ol.",
        ])
        zeka["uyarilar"] = [buy_sell_mesaji, sembol_mesaji] if sembol_mesaji else [buy_sell_mesaji]

    save_json(TRADE_INTELLIGENCE_FILE, zeka)
    logger.info(
        f"🧠 Trade zekası güncellendi | filled={zeka.get('toplam_filled', 0)} "
        f"buy={zeka.get('yon_istatistik', {}).get('buy', 0)} "
        f"sell={zeka.get('yon_istatistik', {}).get('sell', 0)}"
    )


def trade_zekasi_ozeti() -> str:
    zeka = trade_zekasi_yukle()
    st = zeka.get("sembol_istatistik", {}) or {}
    yon = zeka.get("yon_istatistik", {}) or {}
    style = (zeka.get("kullanici_stili", {}) or {}).get("ozet", "")
    dersler = zeka.get("dersler", "")
    uyarilar = zeka.get("uyarilar", []) or []

    st_satirlari = []
    for sym, v in sorted(st.items(), key=lambda x: x[1].get("filled", 0), reverse=True)[:6]:
        st_satirlari.append(
            f"- {sym}: filled={v.get('filled', 0)} buy={v.get('buy', 0)} sell={v.get('sell', 0)}"
        )
    st_metin = "\n".join(st_satirlari) if st_satirlari else "- Henüz sembol istatistiği yok"

    uyarilar_metin = "\n".join([f"- {u}" for u in uyarilar[:5]]) if uyarilar else "-"
    return (
        "TRADE ZEKA ÖZETİ:\n"
        f"Son güncelleme: {zeka.get('son_guncelleme', '-') }\n"
        f"Toplam filled: {zeka.get('toplam_filled', 0)}\n"
        f"Yön dağılımı: buy={yon.get('buy', 0)} sell={yon.get('sell', 0)}\n"
        "Sembol istatistik:\n"
        f"{st_metin}\n\n"
        "Kullanıcı TradingView stili özeti:\n"
        f"{style[:1200] if style else '-'}\n\n"
        "Dersler:\n"
        f"{dersler[:1600] if dersler else '-'}\n\n"
        "Uyarılar:\n"
        f"{uyarilar_metin}"
    )


def fallback_sembol_ve_yon_sec() -> tuple:
    zeka = trade_zekasi_yukle()
    semboller = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]
    stats = zeka.get("sembol_istatistik", {}) or {}
    secilen = sorted(semboller, key=lambda s: (stats.get(s, {}).get("filled", 0), s))[0]

    yon_stats = zeka.get("yon_istatistik", {}) or {}
    buy_n = int(yon_stats.get("buy", 0) or 0)
    sell_n = int(yon_stats.get("sell", 0) or 0)
    taraf = "sell" if buy_n > sell_n else "buy"
    return secilen, taraf


def bugunun_piyasa_arastirmasi(konu: str) -> str:
    """Tavily ile YALNIZCA bugünün verilerini ara.
    Tavily kota aştıysa veya yoksa GPT'nin kendi bilgisiyle devam edilir.
    """
    bugun_iso = datetime.now().strftime("%Y-%m-%d")
    if not tavily:
        return f"[Tavily yok] GPT kendi bilgisiyle analiz yapacak. Tarih: {bugun_iso}"
    konu_l = (konu or "").lower()
    sorgular = [
        f"{bugun_iso} forex majors xauusd central bank cpi fomc nfp impact summary",
    ]
    if "xau" in konu_l or "gold" in konu_l:
        sorgular.append(f"{bugun_iso} xauusd gold usd real yields fed outlook")
    elif "eur" in konu_l or "gbp" in konu_l or "jpy" in konu_l or "forex" in konu_l:
        sorgular.append(f"{bugun_iso} eurusd gbpusd usdjpy macro catalyst")

    sonuclar = []
    tavily_hata = False
    for idx, sorgu in enumerate(sorgular[:2]):
        try:
            res = tavily_search_ekonomik(
                query=sorgu,
                max_results=2,
                cache_key=f"market:{bugun_iso}:{idx}:{sorgu[:120].lower()}",
                ttl_min=TAVILY_MARKET_CACHE_MIN,
            )
            if not res:
                continue
            if res.get("answer"):
                sonuclar.append(f"[Özet] {res['answer']}")
            for r in res.get("results", [])[:2]:
                sonuclar.append(f"[{r.get('url', '')}]\n{r.get('content', '')[:400]}")
        except Exception as e:
            err_str = str(e).lower()
            if "usage limit" in err_str or "plan" in err_str or "429" in err_str:
                tavily_hata = True
            logger.warning(f"Tavily hata ({sorgu[:60]}): {e}")
    if not sonuclar:
        ek = " (Tavily kota aşıldı — GPT dahili bilgisiyle analiz yapılacak)" if tavily_hata else ""
        return f"{konu} için güncel veri alınamadı{ek}. Tarih: {bugun_iso}"
    return "\n\n".join(sonuclar[:8])


def otonom_trade_karari(hesap: dict, gunluk_durum: dict) -> list:
    """GPT-4o + Tavily ile tam otonom trade kararı üret.
    Temel analiz, teknik trend, jeopolitik → JSON emir listesi döndürür.
    KESİN KURAL: Sadece bugünün verilerini kullanır.
    """
    bugun = datetime.now().strftime("%Y-%m-%d")
    saat_str = datetime.now().strftime("%H:%M")
    bakiye = hesap.get("balance", 0)
    equity = hesap.get("equity", 0)
    baslangic = gunluk_durum.get("baslangic_bakiye") or bakiye
    gunluk_kayip_pct = max(0.0, ((baslangic - equity) / baslangic) * 100) if baslangic > 0 else 0.0
    kalan_risk_pct = DAILY_MAX_LOSS_PCT - gunluk_kayip_pct

    if gunluk_kayip_pct >= DAILY_MAX_LOSS_PCT:
        logger.info(f"🛑 Günlük max kayıp ({gunluk_kayip_pct:.1f}% >= {DAILY_MAX_LOSS_PCT}%). Bugün işlem yok.")
        return []

    acilan_islem_sayisi = bugun_gercek_acilan_islem_sayisi()
    if acilan_islem_sayisi >= MAX_DAILY_TRADES:
        logger.info(f"🛑 Günlük işlem limiti dolu ({acilan_islem_sayisi}/{MAX_DAILY_TRADES}). Yeni işlem açılmıyor.")
        return []

    queue_data = trade_queue_yukle()
    aktif = aktif_order_sayisi(queue_data)
    if aktif >= MAX_OPEN_TRADES:
        logger.info(f"📊 Açık işlem limiti dolu: {aktif}/{MAX_OPEN_TRADES}")
        return []

    logger.info(
        f"🤖 Otonom analiz | bakiye={bakiye:.2f} equity={equity:.2f} "
        f"günlük kayıp={gunluk_kayip_pct:.1f}% aktif={aktif}/{MAX_OPEN_TRADES}"
    )
    piyasa_verisi = bugunun_piyasa_arastirmasi("forex gold crypto index market")
    zeka_ozeti = trade_zekasi_ozeti()

    karar_prompt = f"""Bugün: {bugun} | Saat: {saat_str} (Türkiye saati, UTC+3)
Hesap bakiyesi: {bakiye:.2f} USD
Equity: {equity:.2f} USD
Günlük kayıp: {gunluk_kayip_pct:.1f}% (günlük limit: {DAILY_MAX_LOSS_PCT}%)
Kalan risk bütçesi: {kalan_risk_pct:.1f}%
Risk/işlem: max {MAX_RISK_PER_TRADE_PCT}% bakiye
Açık işlem: {aktif}/{MAX_OPEN_TRADES}

BUGÜNKÜ PİYASA VERİSİ ({bugun}):
{piyasa_verisi}

KULLANICI ANALİZ STİLİ VE BİRİKİMLİ ZEKA:
{zeka_ozeti}

---
NOT: Piyasa verisi boşsa veya Tavily erişilemiyorsa — kendi eğitim bilginle {bugun} için en güçlü teknik/temel setup'ı değerlendir. Gerçek veri yokken sadece [] dönme, bilinen trend/seviyelerle analiz yap.
KRİTİK: Forex çift yönlüdür. Sadece buy tarafına veya sadece XAUUSD'ye sabitlenme.
Eğer satış setup'ı daha güçlüyse sell öner. Eğer başka sembolde fırsat güçlüyse onu öner.

Görev:
1. Temel analiz — makro veriler (FOMC, CPI, istihdam, faiz kararları vb.)
2. Teknik trend — destek/direnç seviyeleri, momentum yönü
3. Jeopolitik risk — bilinen güncel gelişmelerin etkisi
4. Spread yüksekse veya sinyal zayıfsa işlem açma
5. Güçlü fırsat yoksa sadece [] döndür
6. Fırsat varsa en fazla {MAX_OPEN_TRADES - aktif} işlem öner

Çıktı: YALNIZCA JSON, başka hiçbir şey yazma:
[
  {{
    "symbol": "XAUUSD",
    "side": "buy",
    "sl_price_dist": 5.0,
    "tp_price_dist": 12.0,
    "neden": "kısa gerekçe"
  }}
]

sl_price_dist / tp_price_dist: giriş fiyatından gerçek fiyat mesafesi.
Örnekler: XAUUSD=5.0 ($5 mesafe) | EURUSD=0.0050 (50 pip) | BTCUSD=200.0 ($200 mesafe).
Fırsat yoksa: []"""

    try:
        yanit = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Deneyimli forex/CFD trader AI'sısın. "
                        "Sadece JSON formatında cevap verirsin. "
                        "Tarih dışı veri kullanmazsın, gerekçesiz işlem önermezsin."
                    ),
                },
                {"role": "user", "content": karar_prompt},
            ],
            max_tokens=1200,
        ).choices[0].message.content.strip()

        json_match = re.search(r'\[.*?\]', yanit, re.DOTALL)
        if not json_match:
            logger.info("🤖 AI trade fırsatı bulmadı (sıkı mod). Esnek moda geçiliyor...")
            kararlar = []
        else:
            kararlar = json.loads(json_match.group())
            if not isinstance(kararlar, list):
                kararlar = []

        if kararlar:
            logger.info(f"🤖 AI {len(kararlar)} fırsat: {[k.get('symbol') for k in kararlar]}")
            return kararlar

        esnek_prompt = f"""Bugün: {bugun} | Saat: {saat_str}
Hesap: bakiye={bakiye:.2f}, equity={equity:.2f}
Risk/işlem: max {MAX_RISK_PER_TRADE_PCT}% | Günlük limit: {DAILY_MAX_LOSS_PCT}%
Açık işlem: {aktif}/{MAX_OPEN_TRADES}

PİYASA VERİSİ ({bugun}):
{piyasa_verisi}

ZEKA ÖZETİ:
{zeka_ozeti}

Kural:
- Piyasa verisi boşsa YINE DE kendi teknik bilginle üret, sadece [] dönme.
- En fazla 1 işlem öner.
- Sadece: XAUUSD, EURUSD, GBPUSD, USDJPY.
- Forex çift yönlüdür; buy/sell arasında fırsata göre seçim yap.
- İlk işlem geçmişte buy oldu diye aynı yöne kitlenme.
- RR en az 1:1.5 olsun (tp_price_dist >= 1.5 * sl_price_dist).
- SL/TP gerçek fiyat mesafesi olarak yaz.

YALNIZCA JSON:
[
  {{
    "symbol": "XAUUSD",
    "side": "buy",
    "sl_price_dist": 5.0,
    "tp_price_dist": 8.0,
    "neden": "kısa gerekçe"
  }}
]"""

        yanit2 = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Pratik ve risk kontrollü forex/CFD trader AI'sısın. "
                        "Yalnızca JSON döndürürsün."
                    ),
                },
                {"role": "user", "content": esnek_prompt},
            ],
            max_tokens=800,
        ).choices[0].message.content.strip()

        json_match2 = re.search(r'\[.*?\]', yanit2, re.DOTALL)
        if not json_match2:
            logger.info("🤖 AI trade fırsatı bulmadı (esnek mod).")
            return []
        kararlar2 = json.loads(json_match2.group())
        if not isinstance(kararlar2, list):
            return []
        if kararlar2:
            logger.info(f"🤖 AI esnek mod {len(kararlar2)} fırsat: {[k.get('symbol') for k in kararlar2]}")
        else:
            logger.info("🤖 AI trade fırsatı bulmadı.")
        return kararlar2
    except Exception as e:
        logger.warning(f"Otonom trade karar hatası: {e}")
        return []


def otonom_trade_dongusu():
    """Her döngüde çağrılır. TRADE_ANALIZ_INTERVAL_MIN dakikada bir piyasa analizi yapar
    ve uygun koşullarda otomatik emir açar.
    """
    global son_trade_analiz_zamani, son_zeka_guncelleme_zamani, ai_firsat_yok_serisi, son_xau_bid, son_fallback_bidler
    if not OTONOM_TRADE_AKTIF:
        return
    if not MT5_CONNECTED:
        return
    if not piyasa_acik_mi():
        logger.info("⏸️  Piyasa şu an kapalı (gece/hafta sonu), trade döngüsü bekleniyor.")
        return
    simdi = time.time()
    if simdi - son_trade_analiz_zamani < TRADE_ANALIZ_INTERVAL_MIN * 60:
        return

    hesap = mt5_hesap_ozeti() or mt5_dosya_hesap_ozeti()
    if not hesap or hesap.get("balance", 0) <= 0:
        logger.info("💰 Hesap bilgisi okunamadı, otonom trade atlanıyor.")
        return

    gunluk_durum = gunluk_durum_yukle()
    if not gunluk_durum.get("baslangic_bakiye"):
        gunluk_durum["baslangic_bakiye"] = hesap["balance"]
        gunluk_durum_kaydet(gunluk_durum)

    queue_data = trade_queue_yukle()
    aktif = aktif_order_sayisi(queue_data)
    baslangic = gunluk_durum.get("baslangic_bakiye") or hesap.get("balance", 0)
    gunluk_kayip_pct = max(0.0, ((baslangic - hesap.get("equity", 0)) / baslangic) * 100) if baslangic > 0 else 0.0

    if simdi - son_zeka_guncelleme_zamani >= TRADE_INTELLIGENCE_GUNCELLE_INTERVAL_MIN * 60:
        trade_zekasi_guncelle()
        son_zeka_guncelleme_zamani = simdi
    kararlar = otonom_trade_karari(hesap, gunluk_durum)
    son_trade_analiz_zamani = simdi

    if kararlar:
        ai_firsat_yok_serisi = 0
    else:
        ai_firsat_yok_serisi += 1

    if (
        not kararlar
        and ai_firsat_yok_serisi >= 1
        and aktif == 0
        and gunluk_kayip_pct < (DAILY_MAX_LOSS_PCT * 0.5)
        and bugun_gercek_acilan_islem_sayisi() < MAX_DAILY_TRADES
    ):
        fallback_symbol, default_side = fallback_sembol_ve_yon_sec()
        sym = sembol_bilgisi_al(fallback_symbol)
        if sym and sym.get("bid", 0) > 0 and sym.get("ask", 0) > 0:
            bid = sym.get("bid", 0)
            ask = sym.get("ask", 0)
            tick_size = sym.get("tick_size", 0.01) or 0.01
            spread_price = (sym.get("spread", 0) or 0) * tick_size
            onceki_bid = son_fallback_bidler.get(fallback_symbol)
            if onceki_bid is None:
                side = default_side
            else:
                side = "buy" if bid >= onceki_bid else "sell"
            son_fallback_bidler[fallback_symbol] = bid
            if fallback_symbol == "XAUUSD":
                son_xau_bid = bid
            sl_dist = max(3.0, round(spread_price * 15, 2))
            tp_dist = round(sl_dist * 1.8, 2)
            kararlar = [{
                "symbol": fallback_symbol,
                "side": side,
                "sl_price_dist": sl_dist,
                "tp_price_dist": tp_dist,
                "neden": "ai_no_signal_fallback_multi_symbol",
            }]
            ai_firsat_yok_serisi = 0
            logger.info(
                f"🤖 Fallback pilot işlem üretildi: {fallback_symbol} {side} sl_dist={sl_dist} tp_dist={tp_dist}"
            )

    for karar in kararlar:
        symbol = str(karar.get("symbol", "")).upper().strip()
        side = str(karar.get("side", "")).lower().strip()
        sl_price_dist = float(karar.get("sl_price_dist") or 0)
        tp_price_dist = float(karar.get("tp_price_dist") or 0)
        neden = str(karar.get("neden", ""))[:100]

        if not symbol or side not in {"buy", "sell"} or sl_price_dist <= 0 or tp_price_dist <= 0:
            logger.warning(f"⚠️ Geçersiz AI kararı atlandı: {karar}")
            continue

        # Sembol bilgisini EA'dan iste — spread, lot limitleri, güncel fiyat
        sym_info = sembol_bilgisi_al(symbol)
        if not sym_info:
            logger.warning(f"⚠️ {symbol} sembol bilgisi alınamadı, işlem açılmıyor.")
            continue

        bid = sym_info.get("bid", 0)
        ask = sym_info.get("ask", 0)
        spread_pts = sym_info.get("spread", 0)
        tick_value = sym_info.get("tick_value", 0)
        tick_size = sym_info.get("tick_size", 0.00001)
        min_lot = sym_info.get("min_lot", 0.01)
        max_lot = sym_info.get("max_lot", 100)
        lot_step = sym_info.get("lot_step", 0.01)
        digits = sym_info.get("digits", 5)

        if bid <= 0 or ask <= 0:
            logger.warning(f"⚠️ {symbol} fiyat yok (bid={bid} ask={ask}), açılmıyor.")
            continue

        # Spread kontrolü: spread, SL mesafesinin %25'inden büyükse aç
        spread_price = spread_pts * tick_size
        if spread_price > sl_price_dist * 0.25:
            logger.warning(
                f"⚠️ {symbol} spread çok yüksek ({spread_price:.5f} > SL'nin %%25'i), işlem açılmıyor."
            )
            continue

        # Risk bazlı lot hesapla
        lot = lot_hesapla(
            hesap["balance"], MAX_RISK_PER_TRADE_PCT, sl_price_dist,
            tick_value, tick_size, lot_step, min_lot, max_lot,
        )

        entry = ask if side == "buy" else bid
        if side == "buy":
            sl = round(entry - sl_price_dist, digits)
            tp = round(entry + tp_price_dist, digits)
        else:
            sl = round(entry + sl_price_dist, digits)
            tp = round(entry - tp_price_dist, digits)

        order = {"symbol": symbol, "side": side, "lot": lot, "sl": sl, "tp": tp}
        kayit, hata = trade_emri_ekle(order, source=f"ai_auto:{neden[:40]}")
        if hata:
            logger.warning(f"❌ AI emri reddedildi ({symbol}): {hata}")
        else:
            logger.info(
                f"🤖 AI işlem: #{kayit['id']} {symbol} {side} lot={lot:.4f} "
                f"sl={sl} tp={tp} | {neden}"
            )
            # acilan_islem_sayisi artık queue'dan canlı hesaplanıyor (failed emirleri saymaz)
            gunluk_durum_kaydet(gunluk_durum)


# ───────────────────────────────────────────────────────────────────────────


def tek_dongu_calistir():
    global son_trade_analiz_zamani
    test_ara_aktif = os.path.exists(TEST_TEK_SEFER_MOLTBOOK_ARA_DOSYASI)

    if test_ara_aktif:
        try:
            os.remove(TEST_TEK_SEFER_MOLTBOOK_ARA_DOSYASI)
        except Exception as e:
            logger.warning(f"TEST flag dosyası tüketilemedi: {e}")
        logger.info("🧪 TEST: Moltbook bu tur erken ara modunda, trade analizi öne alınıyor.")
        son_trade_analiz_zamani = 0.0

    otonom_trade_dongusu()
    trade_emir_yurutucu()

    if ARASTIRMA_MODU:
        if test_ara_aktif:
            logger.info("🧪 TEST: Bu tur Moltbook etkileşimleri pas geçildi.")
        else:
            haftalik_saglik_raporu_kontrolu_ve_gonderimi()
            zamanli_rapor_kontrolu_ve_gonderimi()
            trade_denemesi_tecrubesi_paylas()
            diger_postlari_tara_ve_etkiles()
    if not test_ara_aktif:
        paylas_ve_takil()


def ajanla_konus():
    logger.info("Sohbet modu aktif. Çıkmak için 'cikis' yaz.")
    while True:
        try:
            kullanici_mesaji = input("Sen: ").strip()
        except EOFError:
            print()
            break

        if not kullanici_mesaji:
            continue
        if kullanici_mesaji.lower() in {"cikis", "exit", "quit"}:
            logger.info("Sohbet modu kapatıldı.")
            break

        katı_cevap = katı_gercek_cevap(kullanici_mesaji)
        if katı_cevap:
            print(f"Ajan: {katı_cevap}\n")
            continue

        cevap = ajana_sor("Sohbet Et", gelen_yorum=kullanici_mesaji)
        print(f"Ajan: {cevap}\n")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "chat":
        check_service_health()
        ajanla_konus()
        return 0

    logger.info("--- OVRTHNK AJAN SİSTEMİ AKTİF ---")
    if not kilit_al():
        return 0

    check_service_health()

    try:
        while True:
            try:
                tek_dongu_calistir()
            except Exception as e:
                logger.exception(f"Döngü hatası: {e}")

            if not RUN_CONTINUOUS:
                break

            logger.info(f"Ajan dinlenmede ({LOOP_INTERVAL_SEC // 60} dk)...")
            time.sleep(LOOP_INTERVAL_SEC)
    finally:
        kilidi_birak()

    return 0


if __name__ == "__main__":
    sys.exit(main())