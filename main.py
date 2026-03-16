import json
import logging
import os
import re
import smtplib
import subprocess
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from dotenv import load_dotenv
from openai import OpenAI
import requests
from tavily import TavilyClient

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

# --- YARDIMCI FONKSİYONLAR (MEVCUT) ---
def safe_request(method, url, max_attempts=3, backoff=2, **kwargs):
    attempt = 1
    while attempt <= max_attempts:
        try:
            response = getattr(requests, method)(url, **kwargs)
            return response
        except Exception as e:
            logger.warning(f"{method.upper()} isteği başarısız (deneme {attempt}/{max_attempts}): {e}")
            if attempt == max_attempts: raise
            time.sleep(backoff * attempt)
            attempt += 1

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
    global SUBMOLT_NAME, POST_INTERVAL_SEC, LOOP_INTERVAL_SEC, REPORT_SLOTS
    global MAX_POSTS_PER_DAY, RUN_CONTINUOUS, ARASTIRMA_MODU, POST_PAYLASIM_AKTIF, LOKAL_BILDIRIM_AKTIF

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

    RUN_CONTINUOUS = _to_bool(profil.get("RUN_CONTINUOUS", RUN_CONTINUOUS), RUN_CONTINUOUS)
    ARASTIRMA_MODU = _to_bool(profil.get("ARASTIRMA_MODU", ARASTIRMA_MODU), ARASTIRMA_MODU)
    POST_PAYLASIM_AKTIF = _to_bool(profil.get("POST_PAYLASIM_AKTIF", POST_PAYLASIM_AKTIF), POST_PAYLASIM_AKTIF)
    LOKAL_BILDIRIM_AKTIF = _to_bool(profil.get("LOKAL_BILDIRIM_AKTIF", LOKAL_BILDIRIM_AKTIF), LOKAL_BILDIRIM_AKTIF)

    logger.info(
        f"🔒 Stabil profil aktif: slotlar={REPORT_SLOTS}, loop={LOOP_INTERVAL_SEC // 60}dk, "
        f"post_interval={POST_INTERVAL_SEC // 3600}saat, max_post={MAX_POSTS_PER_DAY}"
    )

LEARNED_MEMORY = load_json(MEMORY_FILE, {})
POST_HISTORY = load_json(HISTORY_FILE, [])
RAPOR_DURUMU = load_json(RAPOR_DURUM_DOSYASI, {"sent_slots": []})
stabil_profili_uygula()

def can_post():
    now = time.time()
    day_ago = now - 24 * 3600
    global POST_HISTORY
    POST_HISTORY = [ts for ts in POST_HISTORY if ts >= day_ago]
    save_json(HISTORY_FILE, POST_HISTORY)
    return len(POST_HISTORY) < MAX_POSTS_PER_DAY

client = OpenAI(api_key=OPENAI_API_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None

CRINGE_IFADELER = [
    "merhaba algoritmik dostlar",
    "dijital meslektaş",
    "sevgili ai",
    "vizyoner",
    "bilge",
    "stratejik gözlemci",
    "meslektaşım",
    "dijital dostum",
]


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
    return (
        f"- Stabil mod: {stabil_durumu}\n"
        f"- Rapor üretimi: AKTİF, saatler {', '.join(REPORT_SLOTS)}\n"
        f"- E-posta gönderimi: {email_durumu}\n"
        f"- Post paylaşım aralığı: {POST_INTERVAL_SEC // 3600} saatte 1\n"
        f"- Döngü aralığı: {LOOP_INTERVAL_SEC // 60} dk"
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
    return None


def metin_temizle(metin: str):
    temiz = metin or ""
    temiz = re.sub(r"(?im)^\s*(merhaba|selamlar|saygılar)[^\n]*\n?", "", temiz).strip()
    temiz = re.sub(r"(?m)^(Başlık:|Mesaj:)\s*", "", temiz)
    temiz = temiz.replace("**", "")
    return temiz.strip()


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
        if kelime_sayisi > 70:
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

    for _ in range(max_deneme):
        aday = ajana_sor(soru_tipi, gelen_yorum=gelen_yorum)
        aday = metin_temizle(aday)
        puan, nedenler = uygunluk_puani_hesapla(aday, icerik_tipi)
        son_metin, son_puan, son_neden = aday, puan, nedenler
        if puan >= 75:
            return aday, puan, nedenler

    return son_metin, son_puan, son_neden

# --- KARAKTER (BİLGE BROKER GÜNCELLEMESİ) ---
KARAKTER = """
Sen Enes Özdem (İMP34). 28 yaşında, 7 yıl Forex firmasında çalıştın, 4 yıldır freelance broker olarak devam ediyorsun.
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
        search_result = tavily.search(query=sorgu, search_depth="advanced")
        context = ""
        for res in search_result['results']:
            context += f"\nKaynak: {res['url']}\nİçerik: {res['content']}\n"
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
    if gelen_yorum:
        prompt += (
            f"\n\nİçerik: '{gelen_yorum}'. Buna en fazla 2 cümleyle kısa, doğal, sakin bir yorum yaz. "
            "Hitap cümlesi kurma, ukalalık yapma, çengel soru zorlaması yapma."
        )
    else:
        prompt += (
            "\n\nFinans/piyasalar/teknoloji üzerine kısa, sade, doğal bir post yaz. "
            "Selamlama cümlesi YAZMA, direkt konuya gir. Hype veya pazarlama dili kullanma. "
            "Aşırı iddialı slogan, teatral ifade ve kendini öven ton kullanma."
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


def yorum_dogrula(verification: dict, headers: dict):
    """Moltbook'un yorum sonrası gönderdiği matematik doğrulama sorusunu çöz ve gönder."""
    try:
        code = verification.get("verification_code")
        challenge = verification.get("challenge_text", "")
        if not code or not challenge:
            return
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


def diger_postlari_tara_ve_etkiles():
    logger.info("🤝 Diğer postları tarayıp etkileşime giriyorum...")
    url = f"https://www.moltbook.com/api/v1/posts?submolt_name={SUBMOLT_NAME}&limit=5"
    headers = {"Authorization": f"Bearer {MOLTBOOK_API_KEY}"}
    res = safe_request("get", url, headers=headers)
    if res.status_code != 200:
        logger.warning(f"Postlar çekilemedi: {res.status_code}")
        return

    posts = res.json().get("posts", [])
    for post in posts:
        if post.get("author", {}).get("username") == "ovrthnk_agent":
            continue

        yorum_kaynagi = post.get("content", "")[:600]
        cevap, puan, nedenler = uygun_icerik_uret("Yorumu Cevapla", gelen_yorum=yorum_kaynagi)
        if puan < 75:
            logger.info(f"⛔ Yorum atlanıyor (uygunluk puanı {puan}/100): {', '.join(nedenler) if nedenler else 'düşük kalite'}")
            continue
        comment_url = f"https://www.moltbook.com/api/v1/posts/{post.get('id')}/comments"
        yorum_res = safe_request("post", comment_url, json={"content": cevap}, headers=headers)
        if yorum_res.status_code in (200, 201):
            logger.info(f"💬 Yorum bırakıldı: {post.get('id')} (puan {puan}/100)")
            data = yorum_res.json()
            verification = data.get("comment", {}).get("verification") or data.get("verification")
            if verification:
                yorum_dogrula(verification, headers)
        else:
            logger.warning(f"Yorum başarısız: {yorum_res.status_code} {yorum_res.text[:200]}")
        time.sleep(5)


def paylas_ve_takil():
    if not POST_PAYLASIM_AKTIF:
        return

    now = time.time()
    last_post_ts = POST_HISTORY[-1] if POST_HISTORY else 0
    gecen_sure = now - last_post_ts
    if gecen_sure < POST_INTERVAL_SEC:
        kalan_dk = int((POST_INTERVAL_SEC - gecen_sure) // 60)
        logger.info(f"🛡️ Post uykusu: {kalan_dk} dk kaldı.")
        return

    if not can_post():
        logger.info("Günlük post limiti doldu.")
        return

    logger.info("🕒 Post zamanı geldi, içerik hazırlanıyor...")
    yeni_post, puan, nedenler = uygun_icerik_uret("Yeni Post Oluştur")
    if puan < 78:
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


def tek_dongu_calistir():
    if ARASTIRMA_MODU:
        zamanli_rapor_kontrolu_ve_gonderimi()
        diger_postlari_tara_ve_etkiles()
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