#!/usr/bin/env python3
"""GovWatch: παρακολούθηση ανακοινώσεων υπουργείων/φορέων.
Χρήση:
  python monitor.py run            # ένας κύκλος ελέγχου
  python monitor.py run --every 30 # συνεχής έλεγχος κάθε 30 λεπτά
  python monitor.py digest         # περίληψη τελευταίων 24 ωρών (+αρχείο digest_ΗΜΕΡΑ.md)
  python monitor.py publish        # ανεβάζει τώρα το site (φάκελος site) στο Netlify
"""
import argparse, hashlib, io, json, os, re, sqlite3, time, unicodedata, zipfile
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import feedparser
except ImportError:
    feedparser = None

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "seen.db")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
}

# Λέξεις-κλειδιά (χωρίς τόνους, μόνο ρίζες)
GREEN = ["επιδομ", "προγραμμ", "επιστροφ", "ενισχυσ", "αποζημιωσ", "επιχορηγ",
         "voucher", "βαουτσερ", "καταρτισ", "δικαιουχ", "αιτησ", "προθεσμ", "εισφορ", "συνταξ",
         "δοσει", "δοσεων", "ρυθμιση οφειλ", "προκαταβολ"]
YELLOW = ["προσληψ", "προκηρυξ", "θεσει", "εργασι", "διορισμ", "αναπληρωτ",
          "ασεπ", "εκπτωσ", "παροχ", "μοριοδοτ", "πληρωμ"]
ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴"}

# Συντάξεις & ασφαλιστικά (ρίζες χωρίς τόνους) — ό,τι παρακολουθεί ένας εργατολόγος
PENSION = ["συνταξ", "ενσημ", "ημερων ασφαλισ", "ημερες ασφαλισ", "ετη ασφαλισ", "χρονια ασφαλισ",
           "οριο ηλικιασ", "ορια ηλικιασ", "ηλικιακ", "εφαπαξ", "επικουρικ", "τεκα", "εκασ",
           "χηρει", "αναπηρι", "διαδοχικ", "πλασματικ", "εξαγορ", "βαρεα", "βαε", "αναδρομικ",
           "προσωρινη συνταξ", "κεαο", "ρυθμιση οφειλ", "ασφαλιστικ", "εισφορ", "κυρια συνταξ",
           "εθνικη συνταξ", "ανταποδοτικ", "προσαυξησ", "περικοπ", "προσωπικη διαφορα", "αποζημιωσ απολυσ"]


def is_pension(title, src):
    t = norm(title)
    return src.get("topic") == "syntaxeis" or any(k in t for k in PENSION)


def log_pension(src, title, url):
    """Αρχείο με όλες τις αλλαγές για συντάξεις (για τον υπολογιστή σύνταξης και τα βίντεο)."""
    with open(os.path.join(HERE, "syntaxeis_log.md"), "a", encoding="utf-8") as f:
        f.write(f"- {datetime.now():%d/%m/%Y %H:%M} · **{src['name']}** · {title}\n  {url}\n")


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).replace("ς", "σ")


# ---------- Ομαδοποίηση ίδιων θεμάτων & φίλτρο θορύβου ----------
STOPW = set(("ποιοι ποιεσ ποιουσ ποιοσ ποια ποιο ποτε πωσ μεχρι εωσ ολεσ ολοι ολα ολουσ αναλυτικα οσοι οσεσ "
             "ακομη ακομα μετα μεσα απο προσ στισ στουσ στην στον στο στα των την τον του τησ ειναι εχουν θα δεν "
             "αλλα ομωσ νεα νεο νεεσ νεοσ νεων τωρα σημερα αυριο αυτα αυτο ηδη μονο πολυ μπαινουν μενουν εκτοσ "
             "αλλαζει αλλαζουν ψιλα γραμματα κερδισμενοι δικαιουχοι δικαιουχων ποσα ευρω").split())
GENERIC = set("πληρω πληρ επιδο επιδ δυπα εφκα ευρω συντα συντ οκτωβ οκτω σεπτε σεπτ δικαι δικα χρεη οφειλ οφει".split())
# Θόρυβος: θέματα εκτός Ελλάδας / άσχετα (ρίζες χωρίς τόνους)
NOISE_WORDS = ["τουρκι", "γαλλι", "ρουμανι", "βιετναμ", "vietnam", "κυπρ", "καιροσ", "κακοκαιρ", "εμυ ", "καταιγιδ",
               "red code", "visa", "mastercard", "space hellas", "τζιροσ", "μετοχ", "χρηματιστηρ", "ποδοσφαιρ"]
# Κυπριακά / ξένα site (ίδιες λέξεις «επίδομα», αλλά δεν αφορούν την Ελλάδα)
NOISE_SITES = ["sigmalive", "philenews", "πολιτησ", "politis", "economy today", "economytoday", "reporter.com.cy",
               "alphanews.live", "omegalive", "kathimerini.com.cy", "cyprus", "offsite", "brief.com.cy",
               "stockwatch", "vietnam", ".cy"]


def is_noise(title, site=""):
    t, s = norm(title), norm(site)
    m = re.search(r"\s[-–]\s([^-–]{2,40})$", title)
    tail = norm(m.group(1)) if m else ""
    return any(k in t for k in NOISE_WORDS) or any(k in s or k in tail for k in NOISE_SITES)


# ---------- Φίλτρο «όφελος για τον κόσμο» (για τις πηγές ειδήσεων και το Ραντάρ) ----------
# Κρατάμε ΜΟΝΟ ό,τι αφορά χρήματα/όφελος για τον πολίτη: επιδόματα, χρηματοδοτήσεις, προγράμματα,
# πληρωμές, επιστροφές, εκπτώσεις, ρυθμίσεις χρεών, θέσεις εργασίας.
BENEFIT = ["επιδομ", "επιδοτ", "ενισχυσ", "χρηματοδοτ", "πληρωμ", "πληρων", "πληρωθ", "ενσημ", "καταβολ", "προκαταβολ",
           "επιστροφ", "αποζημιωσ", "εκπτωσ", "εφαπαξ", "voucher", "βαουτσερ", "κουπον", "επιταγ",
           "μπονουσ", "bonus", "δωρο ", "δωρου", "αυξησ", "αναδρομ", "προγραμμ", "αιτησ", "πλατφορμ",
           "δικαιουχ", "δικαιουνται", "δοσει", "δοσεω", "ρυθμισ", "κουρεμ", "διαγραφ", "απαλλαγ",
           "φοροελαφρ", "μειωση φορ", "μειωσεισ φορ", "υποτροφ", "καταρτισ", "προσληψ", "θεσεισ εργασ",
           "θεσεων εργασ", "θεσεισ πληρουσ", "ανεργ", "συνταξ", "παροχ", "κοινωνικο οικιακο", "κοτ ",
           "δωρεαν", "ενοικι", "θερμανσ", "επιχορηγ", "μικροπιστ", "δανει", "επιδοτουμεν", "ταμειο ανακαμψ",
           "εσπα", "a21", "α21", "οπεκα", "δυπα"]
# Ό,τι δεν θέλουμε ποτέ: εγκλήματα, ατυχήματα, θάνατοι, έλεγχοι/πρόστιμα, κουτσομπολιό
HARM = ["σκοτωθ", "σκοτωσ", "νεκρ", "θανατ", "πεθαν", "τραυματ", "δολοφον", "συλληψ", "συνεληφθ",
        "ατυχημ", "τροχαι", "πυρκαγ", "φωτια", "εγκλημ", "ληστ", "κλοπ", "κλεψ", "βιασ", "ξυλοδαρ",
        "απατ", "σοκ", "τραγωδ", "κηδει", "πνιγ", "κακοκαιρ", "σεισμ", "προστιμ", "λουκετ", "σαφαρι",
        "ελεγχοι", "ελεγχων", "παραβατ", "φοροδιαφυγ", "χωρισ αποδειξ", "κατασχεσ", "πλειστηριασ"]


def is_benefit(title):
    t = norm(clean_title(title))
    words = " " + re.sub(r"[^a-zα-ω0-9]+", " ", t) + " "
    # οι «κακές» λέξεις μετρούν μόνο στην αρχή λέξης (αλλιώς το «νο-σοκ-ομείο» θα έπιανε το «σοκ»)
    return any(k in t for k in BENEFIT) and not any(" " + k in words for k in HARM)


# ---------- Φίλτρο για το SITE (01/10) ----------
# Στο site μπαίνει ΜΟΝΟ ό,τι φέρνει χρήματα/όφελος στον πολίτη (επιδόματα, πληρωμές, προγράμματα,
# θέσεις εργασίας, εκπτώσεις). ΟΧΙ διακηρύξεις, δημοπρασίες, μισθώσεις ακινήτων, δικαστικά,
# εσωτερικά θέματα υπηρεσιών (αποσπάσεις, θέσεις ευθύνης), συναντήσεις και συνεντεύξεις υπουργών.
SITE_EXTRA = ["ανακαινιζ", "σπιτι μου", "εξοικονομ", "κατασκην", "ωφελουμεν", "προσλαμβαν", "θεσεισ εργασ"]
SITE_EXCLUDE = ["διακηρυξ", "δημοπρασ", "διαγωνισμ", "μισθωσ", "μειοδοτ", "πλειοδοτ", "προμηθει",
                "αναθεσ", "κατακυρωσ", "τευχη δημοπρ", "εκδικασ", "εφετει", "δικαστ", "αγωγη ", "αγωγησ",
                "θεσεων ευθυνησ", "θεσεισ ευθυνησ", "αποσπασ", "ανακλησ", "μεταθεσ", "συνεδριασ",
                "συναντησ", "συνεντευξ", "ημεριδ", "δελτιο τιμων", "συγκροτησ", "ορισμοσ μελων",
                "εκθεση για", "παραχωρησ ακινητ", "εκποιησ",
                # ΦΙΛΤΡΑ «ΕΠΙΔΟΜΑΤΑ ΤΩΡΑ» (01/10, φίλτρο 1): όχι επισκέψεις, εγκαίνια, εκδηλώσεις, κομματικά
                "επισκεψ", "περιοδει", "εγκαινι", "χαιρετισμ", "συλλυπητ", "συγχαρ", "βραβευσ", "τελετ",
                "εκδηλωσ", "δεξιωσ", "αντιπολιτευσ", "κομματ", "ποδοσφαιρ", "αθλητ"]


def is_for_site(title):
    """True αν η ανακοίνωση αξίζει να μπει στο site «Επιδόματα Τώρα»."""
    t = norm(title)  # ολόκληρος ο τίτλος (το clean_title κόβει λάθος τίτλους με « - »)
    words = " " + re.sub(r"[^a-zα-ω0-9]+", " ", t) + " "
    if any(k in t for k in SITE_EXCLUDE) or any(" " + k in words for k in HARM):
        return False
    return any(k in t for k in BENEFIT) or any(k in t for k in SITE_EXTRA)


def clean_title(t):
    """Βγάζει το « - Όνομα site» από το τέλος των τίτλων ειδήσεων."""
    return re.sub(r"\s+[-–]\s+[^-–]{2,40}$", "", t).strip()


def title_tokens(t):
    out = set()
    for x in re.findall(r"[a-zα-ω0-9]+", norm(clean_title(t))):
        if x in STOPW:
            continue
        if x.isdigit():
            if len(x) >= 2:
                out.add(x)
        elif len(x) >= 4:
            out.add(x[:4] if len(x) < 7 else x[:5])
    return out


def similarity(a, b):
    if not a or not b:
        return 0
    common = a & b
    i = len(common) - 0.5 * len(common & GENERIC)
    return i / min(len(a), len(b)) if i >= 2 else 0


SAME_STORY = 0.45


def cluster(items, key=lambda x: x["tok"]):
    """Ομαδοποιεί τίτλους που λένε το ίδιο θέμα. items: παλιότερο → νεότερο."""
    groups = []
    for it in items:
        tk = key(it)
        best, bs = None, 0
        for g in groups:
            v = max(similarity(tk, key(x)) for x in g[:8])
            if v > bs:
                best, bs = g, v
        if best is not None and bs >= SAME_STORY:
            best.append(it)
        else:
            groups.append([it])
    return groups


def priority(title):
    t = norm(title)
    if any(k in t for k in GREEN):
        return "green"
    if any(k in t for k in YELLOW):
        return "yellow"
    return "red"


def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS items(
        id TEXT PRIMARY KEY, source TEXT, title TEXT, url TEXT,
        priority TEXT, first_seen TEXT)""")
    return con


# Θεματικά bot: Εφορία/ΑΑΔΕ και ΔΕΗ/ρεύμα
TOPIC_TAG = {
    "eforia": "💶 ΕΦΟΡΙΑ / ΑΑΔΕ\n",
    "dei": "⚡ ΔΕΗ / ΡΕΥΜΑ\n",
    "radar": "📡 ΡΑΝΤΑΡ\n",
}
# Ραντάρ: στέλνει στο Telegram ΜΟΝΟ αν υπάρχει telegram_radar.txt με chat id· αλλιώς φαίνεται μόνο στη σελίδα ειδοποιήσεων
TOPIC_CHAT_FILE = {"eforia": "telegram_eforia.txt", "dei": "telegram_dei.txt", "radar": "telegram_radar.txt"}
MAX_NEWS_PER_RUN = 5  # όριο ειδοποιήσεων ανά κύκλο για τις πηγές ειδήσεων (να μη γεμίζει το Telegram)


def topic_chat(topic):
    """Αν υπάρχει telegram_eforia.txt / telegram_dei.txt με chat id, στέλνει εκεί· αλλιώς στο κύριο."""
    fn = TOPIC_CHAT_FILE.get(topic)
    if fn and os.path.exists(os.path.join(HERE, fn)):
        with open(os.path.join(HERE, fn), encoding="utf-8") as f:
            v = f.read().strip()
        return v or None
    return None


def fetch_rss(content):
    import xml.etree.ElementTree as ET
    items = []
    root = ET.fromstring(content)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        srcel = it.find("source")
        site = ((srcel.get("url") or "") + " " + (srcel.text or "")) if srcel is not None else ""
        if title and link and not is_noise(title, site):
            items.append((title, link))
    return items


def fetch_dei():
    """Δελτία Τύπου ΔΕΗ (η σελίδα τα φορτώνει από αυτό το API)."""
    base = "https://www.ppcgroup.com"
    h = dict(HEADERS, **{"Content-Type": "application/json", "Accept": "application/json",
                         "Referer": base + "/el/omilos-dei/grafeio-typou/deltia-typou"})
    r = requests.post(base + "/umbraco/api/articleapi/getgroupedarticleslist?currentpageid=525747&culture=el-GR",
                      headers=h, json={"page": 1, "roots": ["525747"], "tags": []}, timeout=30)
    r.raise_for_status()
    return [(" ".join(x["tl"].split()), urljoin(base, x["url"])) for x in r.json().get("data", [])]


def fetch_items(src):
    if src.get("type") == "dei_api":
        return fetch_dei()
    r = requests.get(src["url"], headers=HEADERS, timeout=30)
    r.raise_for_status()
    items = []
    if src.get("type") == "rss":
        items = fetch_rss(r.content)
        if src.get("keywords"):
            items = [(t, u) for t, u in items if any(k in norm(t) for k in src["keywords"])]
        if src.get("exclude"):
            items = [(t, u) for t, u in items if not any(k in norm(t) for k in src["exclude"])]
        if src.get("private"):  # ειδήσεις & Ραντάρ: μόνο ό,τι έχει όφελος/χρήματα για τον κόσμο
            items = [(t, u) for t, u in items if is_benefit(t)]
        return items
    else:
        soup = BeautifulSoup(r.content, "html.parser")
        for a in soup.select(src.get("selector", "a")):
            title = " ".join(a.get_text().split())
            href = a.get("href")
            if href and "redirect-banner" in href:
                continue
            if href and len(title) >= src.get("min_title", 25):
                items.append((title, urljoin(src["url"], href)))
        if src.get("exclude"):
            items = [(t, u) for t, u in items if not any(k in norm(t) for k in src["exclude"])]
    return items


def tg_config():
    """Διαβάζει token και chat id από το telegram.txt (γραμμή 1: token, γραμμή 2: chat id)."""
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    path = os.path.join(HERE, "telegram.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = [l.strip() for l in f.read().splitlines() if l.strip()]
        if lines:
            token = lines[0]
        if len(lines) > 1:
            chat = lines[1]
    return token, chat


SYN_CHAT_FILE = os.path.join(HERE, "telegram_syntaxeis.txt")


def syn_chat():
    """Chat id του καναλιού «Συντάξεις». Αν δεν έχει βρεθεί ακόμα, το ψάχνει μόνο του:
    κανάλι/ομάδα με «συνταξ» στο όνομα όπου το bot είναι μέλος/διαχειριστής."""
    if os.path.exists(SYN_CHAT_FILE):
        with open(SYN_CHAT_FILE, encoding="utf-8") as f:
            v = f.read().strip()
        if v:
            return v
    token, _ = tg_config()
    if not token:
        return None
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
    except requests.RequestException:
        return None
    for u in reversed(r.get("result", [])):
        for key in ("channel_post", "my_chat_member", "message"):
            chat = (u.get(key) or {}).get("chat") or {}
            if chat.get("type") in ("channel", "supergroup", "group") and "συνταξ" in norm(chat.get("title", "")):
                with open(SYN_CHAT_FILE, "w", encoding="utf-8") as f:
                    f.write(str(chat["id"]))
                print(f"✅ Βρέθηκε το κανάλι «{chat.get('title')}» για τις συντάξεις.")
                notify("✅ Το GovWatch θα στέλνει εδώ όλες τις ειδοποιήσεις για συντάξεις.", chat=str(chat["id"]))
                return str(chat["id"])
    return None


def notify(text, chat=None):
    token, main_chat = tg_config()
    chat = chat or main_chat
    if not (token and chat):
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text}, timeout=20)
        return r.ok
    except requests.RequestException as e:
        print("Telegram error:", e)
        return False


# ---- Δελτίο GovWatch: αποστολή deltio.txt στο Telegram και αρχειοθέτηση στο deltia ----

DELTIO_FILE = os.path.join(HERE, "deltio.txt")
DELTIA_DIR = os.path.join(HERE, "deltia")


def send_deltio():
    """Αν υπάρχει deltio.txt: το στέλνει στο Telegram (σε κομμάτια, όριο 4096 χαρακτήρες)
    και μετά το μετακινεί στο deltia/deltio_ΕΕΕΕ-ΜΜ-ΗΗ_ΩΩΛΛ.txt.
    Αν η αποστολή αποτύχει, το αφήνει στη θέση του για να ξαναδοκιμάσει."""
    if not os.path.exists(DELTIO_FILE):
        return
    # Αν το αρχείο γράφτηκε πριν από λιγότερο από 10 δευτερόλεπτα, περίμενε (μπορεί να γράφεται ακόμα)
    if time.time() - os.path.getmtime(DELTIO_FILE) < 10:
        return
    with open(DELTIO_FILE, encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return

    # Χωρίζει σε κομμάτια έως 3900 χαρακτήρες, κόβοντας σε κενή γραμμή όπου γίνεται
    chunks, cur = [], ""
    for block in text.split("\n\n"):
        piece = (cur + "\n\n" + block) if cur else block
        if len(piece) <= 3900:
            cur = piece
        else:
            if cur:
                chunks.append(cur)
            while len(block) > 3900:          # σπάνιο: ένα τεράστιο κομμάτι χωρίς κενές γραμμές
                chunks.append(block[:3900])
                block = block[3900:]
            cur = block
    if cur:
        chunks.append(cur)

    for c in chunks:
        if not notify(c):
            print("[!] Το δελτίο δεν στάλθηκε, θα ξαναδοκιμάσω.")
            return
        time.sleep(1)

    os.makedirs(DELTIA_DIR, exist_ok=True)
    name = "deltio_" + datetime.now().strftime("%Y-%m-%d_%H%M") + ".txt"
    os.replace(DELTIO_FILE, os.path.join(DELTIA_DIR, name))
    print(f"📋 Δελτίο στάλθηκε στο Telegram και αρχειοθετήθηκε: deltia/{name}")


def tg_setup():
    token, _ = tg_config()
    if not token:
        print("Βάλε πρώτα το token στην πρώτη γραμμή του αρχείου telegram.txt")
        return
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
    except requests.RequestException as e:
        print("Σφάλμα σύνδεσης:", e)
        return
    if not r.get("ok"):
        print("Το token δεν είναι σωστό. Έλεγξε ότι το αντέγραψες ολόκληρο.")
        return
    chats = [u["message"]["chat"]["id"] for u in r.get("result", []) if "message" in u]
    if not chats:
        print("Δεν βρήκα μήνυμα. Άνοιξε το bot σου στο Telegram, πάτα Start, γράψε 'γεια' και ξανατρέξε αυτή την εντολή.")
        return
    with open(os.path.join(HERE, "telegram.txt"), "w", encoding="utf-8") as f:
        f.write(f"{token}\n{chats[-1]}\n")
    ok = notify("✅ Το GovWatch συνδέθηκε με το Telegram!")
    print("Έτοιμο! Έλεγξε το Telegram σου." if ok else "Αποθηκεύτηκε, αλλά το μήνυμα δεν στάλθηκε.")


def run_once(only_fast=False):
    """only_fast=True: ελέγχει μόνο τις πηγές για συντάξεις/νομοθεσία (fast: true)."""
    with open(os.path.join(HERE, "sources.json"), encoding="utf-8") as f:
        sources = json.load(f)
    try:
        syn_chat()  # βρίσκει μόνο του το κανάλι «Συντάξεις» μόλις δημιουργηθεί
    except Exception as e:
        print("[!] Telegram:", e)
    if only_fast:
        sources = [s for s in sources if s.get("fast")]
        print(f"--- Γρήγορος έλεγχος συντάξεων ({datetime.now():%H:%M}) ---")
    con = db()
    private_names = [x["name"] for x in sources if x.get("private")]
    if only_fast:  # χρειαζόμαστε όλες τις πηγές ειδήσεων για να ξέρουμε τι έχει ήδη σταλεί
        with open(os.path.join(HERE, "sources.json"), encoding="utf-8") as f:
            private_names = [x["name"] for x in json.load(f) if x.get("private")]
    since48 = (datetime.now() - timedelta(hours=48)).isoformat()
    q = ",".join("?" * len(private_names)) or "''"
    recent_news = [title_tokens(t) for (t,) in con.execute(
        f"SELECT title FROM items WHERE first_seen>=? AND source IN ({q})", (since48, *private_names))]

    def already_told(title):
        """True αν το ίδιο θέμα έχει ήδη έρθει από άλλο site τις τελευταίες 48 ώρες."""
        tk = title_tokens(title)
        hit = any(similarity(tk, x) >= SAME_STORY for x in recent_news)
        recent_news.append(tk)
        return hit

    for src in sources:
        try:
            items = fetch_items(src)
        except Exception as e:
            print(f"[!] {src['name']}: {e}")
            continue
        first_run = con.execute("SELECT COUNT(*) FROM items WHERE source=?",
                                (src["name"],)).fetchone()[0] == 0
        new = 0
        sent = 0
        topic = src.get("topic")
        for title, url in items:
            iid = hashlib.sha1((src["name"] + title).encode()).hexdigest()
            if con.execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
                continue
            # Ίδιο link με διαφορετικό τίτλο (π.χ. με/χωρίς ημερομηνία) = ίδια ανακοίνωση
            if url and con.execute("SELECT 1 FROM items WHERE source=? AND url=?", (src["name"], url)).fetchone():
                continue
            if topic == "radar":
                # Ραντάρ: τίτλοι από άλλα site ειδήσεων. Μόνο για σένα — ποτέ στο site.
                con.execute("INSERT INTO items VALUES(?,?,?,?,?,?)",
                            (iid, src["name"], title, url, "yellow",
                             "2000-01-01T00:00:00" if first_run else datetime.now().isoformat()))
                new += 1
                rc = topic_chat("radar")
                if already_told(title):
                    continue
                if not first_run and rc:
                    sent += 1
                    if sent <= MAX_NEWS_PER_RUN:
                        notify(f"{TOPIC_TAG['radar']}{src['name']}\n{title}\n{url}", chat=rc)
                continue
            p = priority(title)
            pension = is_pension(title, src)
            if pension or topic == "nomos":
                p = "green" if pension else "yellow"
            elif topic in TOPIC_TAG and p == "red":
                p = "yellow"  # ό,τι αφορά Εφορία/ΔΕΗ ειδοποιείται πάντα
            if src.get("priority"):  # π.χ. Υπουργικό Συμβούλιο: πάντα σημαντικό
                p = src["priority"]
            con.execute("INSERT INTO items VALUES(?,?,?,?,?,?)",
                        (iid, src["name"], title, url, p,
                         "2000-01-01T00:00:00" if first_run else datetime.now().isoformat()))
            new += 1
            if not first_run and pension:
                log_pension(src, title, url)
            if not first_run and p in ("green", "yellow"):
                if src.get("private") and already_told(title):
                    continue  # ίδιο θέμα από άλλο site — δεν ξαναστέλνεται
                if src.get("private"):  # πηγές ειδήσεων: όριο ανά κύκλο
                    sent += 1
                    if sent > MAX_NEWS_PER_RUN:
                        continue
                if topic in TOPIC_TAG:
                    tag = TOPIC_TAG[topic]
                else:
                    tag = "👴 ΣΥΝΤΑΞΕΙΣ / ΑΣΦΑΛΙΣΤΙΚΑ\n" if pension else ("⚖️ ΝΟΜΟΘΕΣΙΑ\n" if topic == "nomos" else "")
                msg = f"{tag}{ICON[p]} {src['name']}\n{title}\n{url}"
                print(msg, "\n")
                sc = topic_chat(topic) if topic in TOPIC_TAG else (
                    syn_chat() if (pension or topic == "nomos") else None)
                if sc:
                    notify(msg, chat=sc)   # κανάλι «Συντάξεις»
                else:
                    notify(msg)
        con.commit()
        print(f"{src['name']}: {len(items)} βρέθηκαν, {new} νέα" + (" (αρχική καταγραφή)" if first_run else ""))
    write_html()
    if not only_fast:
        try:
            update_popular()
        except Exception as e:
            print("[!] Δημοφιλή:", e)
    try:
        publish()
    except Exception as e:
        print("[!] Site:", e)


# ---------- Αυτόματη ενημέρωση του site «Επιδόματα Τώρα» (Netlify) ----------
SITE = os.path.join(HERE, "site")
DEFAULT_SITE = "epidomata-tora"
AUTO_TEXT = "Νέα ανακοίνωση στην επίσημη σελίδα του φορέα. Πάτα «Πηγή» για όλες τις λεπτομέρειες."
GOATCOUNTER = "https://greekmaster79.goatcounter.com"


def update_popular(days=7, min_views=5):
    """«Δημοφιλή αυτή τη στιγμή»: παίρνει τις πιο διαβασμένες σελίδες επιδομάτων από το GoatCounter
    (token στο goatcounter.txt) και γράφει site/popular.json. Μία φορά κάθε 6 ώρες."""
    tok_path = os.path.join(HERE, "goatcounter.txt")
    out = os.path.join(SITE, "popular.json")
    if not os.path.exists(tok_path):
        return
    if os.path.exists(out) and time.time() - os.path.getmtime(out) < 6 * 3600:
        return
    with open(tok_path, encoding="utf-8-sig") as f:
        token = f.read().strip()
    if not token:
        return
    with open(os.path.join(SITE, "index.html"), encoding="utf-8") as f:
        html = f.read()
    slug_to_id = {slug: bid for bid, slug in re.findall(r'id: "([^"]+)", slug: "([^"]+)"', html)}
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    r = requests.get(f"{GOATCOUNTER}/api/v0/stats/hits", params={"start": start, "limit": 100},
                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=30)
    if r.status_code == 401:
        print("[!] Δημοφιλή: το token του GoatCounter δεν είναι σωστό (goatcounter.txt).")
        return
    r.raise_for_status()
    counts = {}
    for h in r.json().get("hits", []):
        path, n = h.get("path", ""), int(h.get("count") or h.get("count_unique") or 0)
        m = re.match(r"^/epidomata/([^/?#]+)", path)
        bid = slug_to_id.get(m.group(1)) if m else None
        if not bid:  # παλιοί σύνδεσμοι, π.χ. /#b-a21
            m = re.search(r"#b-([^/?#]+)", path)
            bid = m.group(1) if m and m.group(1) in slug_to_id.values() else None
        if bid:
            counts[bid] = counts.get(bid, 0) + n
    ids = [b for b, n in sorted(counts.items(), key=lambda x: -x[1]) if n >= min_views][:6]
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"ids": ids, "days": days, "updated": datetime.now().isoformat(timespec="minutes")}, f, ensure_ascii=False)
    print(f"📈 Δημοφιλή ενημερώθηκαν: {', '.join(ids) or 'δεν υπάρχουν αρκετές προβολές ακόμα'}")


def netlify_config():
    """netlify.txt: γραμμή 1 το token, (προαιρετικά) γραμμή 2 το όνομα του site."""
    for name in ("netlify.txt", "netlify.txt.txt", "netlify"):
        path = os.path.join(HERE, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8-sig") as f:
                lines = [l.strip() for l in f.read().splitlines() if l.strip()]
            if lines:
                return lines[0], (lines[1] if len(lines) > 1 else DEFAULT_SITE)
    return None, DEFAULT_SITE


def write_site_json():
    """Γράφει site/anakoinoseis.json με τις πράσινες/κίτρινες ανακοινώσεις 45 ημερών.
    Επιστρέφει True αν άλλαξε κάτι."""
    con = db()
    since = (datetime.now() - timedelta(days=45)).isoformat()
    # Στο site μπαίνουν ΜΟΝΟ επίσημες πηγές — όχι οι πηγές ειδήσεων ("private": true)
    try:
        with open(os.path.join(HERE, "sources.json"), encoding="utf-8") as f:
            private = {s["name"] for s in json.load(f) if s.get("private")}
    except Exception:
        private = set()
    # ΔΙΟΡΘΩΣΗ 01/10: οι πηγές ειδήσεων εξαιρούνται ΜΕΣΑ στο ερώτημα. Πριν, οι πολλές ειδήσεις
    # «έτρωγαν» το όριο των 120 και στο site έμεναν μόνο οι ανακοινώσεις της ημέρας.
    q = ",".join("?" * len(private)) or "''"
    rows = con.execute("SELECT source,title,url,first_seen FROM items "
                       f"WHERE first_seen>=? AND source NOT IN ({q}) "
                       "ORDER BY first_seen DESC LIMIT 600", (since, *private)).fetchall()
    # ΔΙΟΡΘΩΣΗ 01/10 (β): δεν φιλτράρουμε πια με το χρώμα (π.χ. οι «120 δόσεις» ήταν κόκκινες και χάνονταν)·
    # αποφασίζει μόνο το is_for_site.
    # ΦΙΛΤΡΟ 01/10: μόνο ό,τι αφορά επιδόματα/πληρωμές/προγράμματα (όχι δημοπρασίες, δικαστικά κ.λπ.)
    rows = [r for r in rows if is_for_site(r[1])]
    # ΦΙΛΤΡΟ 8 (01/10): ίδιο θέμα δύο φορές από τον ίδιο φορέα (π.χ. ίδιος τίτλος με ημερομηνία μπροστά)
    # → μένει μία φορά, η νεότερη.
    kept = []
    for r in rows:
        tk = title_tokens(re.sub(r"^\s*[\d.\-/]+\s*[-–]?\s*", "", r[1]))
        if any(k[0] == r[0] and similarity(tk, k[4]) >= 0.8 for k in kept):
            continue
        kept.append((*r, tk))
    rows = [k[:4] for k in kept][:80]
    data = [{"date": fs[:10], "foreas": s, "title": t, "url": u, "text": AUTO_TEXT, "auto": True}
            for s, t, u, fs in rows]
    # Χειροκίνητες ανακοινώσεις (manual.json στον φάκελο govwatch): σημαντικά θέματα με δικό τους κείμενο,
    # ΜΟΝΟ με επίσημη πηγή. Μπαίνουν πρώτα, ταξινομημένα με ημερομηνία.
    mpath = os.path.join(HERE, "manual.json")
    if os.path.exists(mpath):
        try:
            with open(mpath, encoding="utf-8-sig") as f:
                manual = [m for m in json.load(f) if m.get("date", "") >= since[:10]]
            urls = {m.get("url") for m in manual}
            data = sorted(manual + [d for d in data if d["url"] not in urls],
                          key=lambda d: d["date"], reverse=True)
        except Exception as e:
            print("[!] manual.json:", e)
    os.makedirs(SITE, exist_ok=True)
    path = os.path.join(SITE, "anakoinoseis.json")
    new = json.dumps(data, ensure_ascii=False, indent=1)
    old = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if old == new:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    return True


def site_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(SITE):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, SITE).replace(os.sep, "/"))
    return buf.getvalue()


def find_site_id(token, name):
    """Βρίσκει το site στο Netlify με βάση το όνομα (π.χ. epidomata-tora)."""
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get("https://api.netlify.com/api/v1/sites", headers=h,
                     params={"filter": "all", "name": name, "per_page": 100}, timeout=30)
    if not r.ok:
        return None, r.status_code
    short = name.replace(".netlify.app", "")
    for s in r.json():
        if s.get("name") == short or s.get("url", "").rstrip("/").endswith(f"//{short}.netlify.app"):
            return s["id"], 200
    return None, 404


def deploy_netlify():
    token, name = netlify_config()
    if not token:
        print("[i] Site: δεν βρέθηκε token στο netlify.txt — το site δεν ενημερώθηκε.")
        return False
    if not os.path.exists(os.path.join(SITE, "index.html")):
        print("[!] Site: λείπει ο φάκελος site με το index.html.")
        return False
    site_id, code = find_site_id(token, name)
    if code == 401:
        print("[!] Site: το token του Netlify δεν είναι σωστό. Φτιάξε καινούργιο και βάλ' το στο netlify.txt.")
        return False
    if not site_id:
        print(f"[!] Site: δεν βρέθηκε site με όνομα «{name}» στον λογαριασμό Netlify.")
        return False
    r = requests.post(f"https://api.netlify.com/api/v1/sites/{site_id}/deploys",
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/zip"},
                      data=site_zip(), timeout=180)
    if r.ok:
        print(f"🌐 Το site ενημερώθηκε: https://{name.replace('.netlify.app', '')}.netlify.app")
        return True
    if r.status_code == 403 and "credit" in r.text.lower():
        with open(os.path.join(HERE, "netlify_paused.txt"), "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat())
        print("[!] Site: τελείωσαν τα δωρεάν credits του Netlify — το site ΔΕΝ ενημερώνεται. "
              "Νέα προσπάθεια σε 24 ώρες. Οι ειδοποιήσεις και το Telegram δουλεύουν κανονικά.")
        return False
    print(f"[!] Site: σφάλμα Netlify {r.status_code}: {r.text[:200]}")
    return False



# ---------- Cloudflare Pages (κύρια φιλοξενία από 01/10/2026) ----------
CF_API = "https://api.cloudflare.com/client/v4"
CF_PROJECT = "epidomata-tora"
OLD_URL = "https://epidomata-tora.netlify.app"
# Όταν συνδεθεί το domain, αλλάζει μόνο αυτό (π.χ. "https://epidomatatora.gr")
SITE_URL = "https://epidomatatora.gr"
MIN_DEPLOY_GAP = 60 * 60  # το πολύ ένα ανέβασμα την ώρα (εκτός από «python monitor.py publish»)
SKIP_FILES = {"_headers", "_routes.json", ".DS_Store", "Thumbs.db", "desktop.ini"}


def cf_config():
    path = os.path.join(HERE, "cloudflare.txt")
    if not os.path.isfile(path):
        return None, None
    with open(path, encoding="utf-8-sig") as f:
        lines = [l.strip() for l in f.read().splitlines() if l.strip()]
    return (lines[0] if lines else None), (lines[1] if len(lines) > 1 else None)


def blake3_hex(data):
    try:
        import blake3
        return blake3.blake3(data).hexdigest()
    except ImportError:
        from blake3_py import blake3_hex as b3
        return b3(data)


def cf_req(method, path, token, **kw):
    r = requests.request(method, CF_API + path, headers={"Authorization": f"Bearer {token}", **kw.pop("headers", {})},
                         timeout=kw.pop("timeout", 60), **kw)
    try:
        j = r.json()
    except ValueError:
        j = {"success": False, "errors": [{"message": r.text[:200]}]}
    return r.status_code, j


def cf_err(j):
    return "; ".join(e.get("message", "") for e in j.get("errors", [])) or "άγνωστο σφάλμα"


def deploy_cloudflare(token, account):
    import base64, mimetypes
    if not account:
        code, j = cf_req("GET", "/accounts", token)
        if not j.get("success") or not j.get("result"):
            print(f"[!] Site: ο κωδικός Cloudflare δεν δουλεύει ({cf_err(j)}). Έλεγξε το cloudflare.txt.")
            return False
        account = j["result"][0]["id"]
    # Το project (φτιάχνεται αυτόματα την πρώτη φορά)
    code, j = cf_req("GET", f"/accounts/{account}/pages/projects/{CF_PROJECT}", token)
    if code == 404 or (not j.get("success") and "not found" in cf_err(j).lower()):
        code, j = cf_req("POST", f"/accounts/{account}/pages/projects", token,
                         json={"name": CF_PROJECT, "production_branch": "main"})
        print("🆕 Δημιουργήθηκε το project στο Cloudflare Pages." if j.get("success") else "")
    if not j.get("success"):
        print(f"[!] Site: Cloudflare — {cf_err(j)}")
        return False
    sub = j["result"].get("subdomain") or f"{CF_PROJECT}.pages.dev"
    base = SITE_URL or f"https://{sub}"
    # Αρχεία + hash (όπως το επίσημο εργαλείο wrangler)
    files = {}
    for root, _, fns in os.walk(SITE):
        for fn in fns:
            if fn in SKIP_FILES or fn.startswith("."):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, SITE).replace(os.sep, "/")
            with open(full, "rb") as f:
                data = f.read()
            ext = os.path.splitext(fn)[1][1:]
            if ext in ("html", "xml", "txt", "json", "webmanifest"):
                data = data.replace(OLD_URL.encode(), base.encode())
            b64 = base64.b64encode(data).decode()
            files["/" + rel] = {"hash": blake3_hex((b64 + ext).encode())[:32], "b64": b64,
                                "type": mimetypes.guess_type(fn)[0] or "application/octet-stream"}
    code, j = cf_req("GET", f"/accounts/{account}/pages/projects/{CF_PROJECT}/upload-token", token)
    if not j.get("success"):
        print(f"[!] Site: Cloudflare upload-token — {cf_err(j)}")
        return False
    jwt = j["result"]["jwt"]
    hashes = sorted({v["hash"] for v in files.values()})
    code, j = cf_req("POST", "/pages/assets/check-missing", jwt, json={"hashes": hashes})
    missing = set(j.get("result") or []) if j.get("success") else set(hashes)
    todo = {v["hash"]: v for v in files.values() if v["hash"] in missing}
    bucket, size = [], 0
    for h, v in list(todo.items()) + [(None, None)]:
        if v is not None:
            bucket.append({"key": h, "value": v["b64"], "metadata": {"contentType": v["type"]}, "base64": True})
            size += len(v["b64"])
        if bucket and (v is None or size > 30_000_000 or len(bucket) >= 1000):
            code, j = cf_req("POST", "/pages/assets/upload", jwt, json=bucket, timeout=300)
            if not j.get("success"):
                print(f"[!] Site: Cloudflare upload — {cf_err(j)}")
                return False
            bucket, size = [], 0
    cf_req("POST", "/pages/assets/upsert-hashes", jwt, json={"hashes": hashes})
    manifest = {p: v["hash"] for p, v in files.items()}
    code, j = cf_req("POST", f"/accounts/{account}/pages/projects/{CF_PROJECT}/deployments", token,
                     files={"manifest": (None, json.dumps(manifest)), "branch": (None, "main")}, timeout=180)
    if j.get("success"):
        print(f"🌐 Το site ενημερώθηκε: {base}")
        return True
    print(f"[!] Site: Cloudflare deploy — {cf_err(j)}")
    return False


def deploy():
    """Cloudflare Pages αν υπάρχει κωδικός στο cloudflare.txt· αλλιώς Netlify (παλιά λύση)."""
    token, account = cf_config()
    if token:
        try:
            return deploy_cloudflare(token, account)
        except requests.RequestException as e:
            print("[!] Site: Cloudflare — πρόβλημα σύνδεσης:", e)
            return False
    return deploy_netlify()


def publish(force=False):
    """Ανεβάζει το site μόνο όταν υπάρχουν νέες ανακοινώσεις (ή με force)."""
    write_site_json()
    h = hashlib.sha1()  # αποτύπωμα όλου του φακέλου site (ανακοινώσεις + σχέδιο)
    for root, _, files in sorted(os.walk(SITE)):
        for fn in sorted(files):
            full = os.path.join(root, fn)
            h.update(os.path.relpath(full, SITE).encode())
            with open(full, "rb") as f:
                h.update(f.read())
    digest_now = h.hexdigest()
    mark = os.path.join(HERE, "last_deploy.txt")
    last = open(mark).read().strip() if os.path.exists(mark) else ""
    if digest_now == last and not force:
        return False
    tmark = os.path.join(HERE, "last_upload_time.txt")
    if not force and os.path.exists(tmark) and time.time() - os.path.getmtime(tmark) < MIN_DEPLOY_GAP:
        return False  # έγινε ανέβασμα πριν από λιγότερο από μία ώρα — θα γίνει στον επόμενο κύκλο
    pause = os.path.join(HERE, "netlify_paused.txt")
    if not force and not cf_config()[0] and os.path.exists(pause) and time.time() - os.path.getmtime(pause) < 24 * 3600:
        return False  # το Netlify μπλόκαρε τα deploys (τελείωσαν τα credits) — δεν ξαναδοκιμάζουμε για 24 ώρες
    ok = deploy()
    if ok and os.path.exists(pause):
        os.remove(pause)
    if ok:
        with open(mark, "w") as f:
            f.write(digest_now)
        with open(tmark, "w") as f:
            f.write(datetime.now().isoformat())
    return ok


def write_html():
    """Σελίδα notifications.html (7 ημέρες).
    - Επίσημες ανακοινώσεις: μία κάρτα η καθεμία.
    - Ειδήσεις & Ραντάρ: ΟΜΑΔΟΠΟΙΗΜΕΝΕΣ — ίδιο θέμα από πολλά site = μία κάρτα «Θέμα» με αριθμό άρθρων.
    Τι έχεις δει/κρύψει το θυμάται ο browser σου (localStorage)."""
    con = db()
    since = (datetime.now() - timedelta(days=7)).isoformat()
    rows = con.execute("SELECT id,source,title,url,priority,first_seen FROM items WHERE first_seen>=? "
                       "ORDER BY first_seen ASC", (since,)).fetchall()
    try:
        with open(os.path.join(HERE, "sources.json"), encoding="utf-8") as f:
            srcs = json.load(f)
    except Exception:
        srcs = []
    topics = {x["name"]: x.get("topic", "") for x in srcs}
    private = {x["name"] for x in srcs if x.get("private")}
    official, news, seen_titles = [], [], set()
    for iid, s, t, u, p, ts in rows:
        top = topics.get(s, "")
        if s in private:
            if is_noise(t) or not is_benefit(t) or t in seen_titles:  # θόρυβος / χωρίς όφελος / διπλό
                continue
            seen_titles.add(t)
            news.append({"id": iid[:12], "s": s, "t": t, "u": u, "ts": ts[:16], "top": top, "tok": title_tokens(t)})
        else:
            if not top and is_pension(t, {}):
                top = "syntaxeis"
            official.append({"id": iid[:12], "s": s, "t": t, "u": u, "p": p, "ts": ts[:16], "top": top,
                             "tok": title_tokens(t)})
    stories = []
    for g in cluster(news):
        tops = sorted({x["top"] for x in g if x["top"] != "radar"} |
                      ({"syntaxeis"} if any("Συντάξ" in x["s"] for x in g) else set()))
        # Υπάρχει επίσημη ανακοίνωση για το ίδιο θέμα;
        off = None
        for o in reversed(official):
            if max(similarity(o["tok"], x["tok"]) for x in g[:8]) >= SAME_STORY:
                off = {"t": o["t"], "u": o["u"], "s": o["s"]}
                break
        sites = len({re.sub(r"^.*\s[-–]\s", "", x["t"]) for x in g})
        stories.append({"id": "c" + g[0]["id"], "t": clean_title(g[0]["t"]), "n": len(g), "sites": sites,
                        "ts": g[-1]["ts"], "tops": tops, "off": off,
                        "items": [{"id": x["id"], "t": x["t"], "u": x["u"], "ts": x["ts"]} for x in reversed(g)]})
    for o in official:
        del o["tok"]
    payload = json.dumps({"official": official[::-1], "stories": stories}, ensure_ascii=False).replace("</", "<\\/")
    html = """<!DOCTYPE html><html lang="el"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>GovWatch</title><style>
body{font-family:Segoe UI,Arial,sans-serif;max-width:860px;margin:18px auto;padding:0 12px;background:#f4f6f9;color:#14202e}
h2{margin:0}.top{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.muted{color:#56657a;font-size:13px}.bar{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}
.bar button,.act{border:1px solid #cfd8e3;background:#fff;border-radius:999px;padding:6px 12px;font-weight:600;cursor:pointer;font-size:13.5px}
.bar button.on{background:#0d2b52;color:#fff;border-color:#0d2b52}.act.main{background:#1a66e0;color:#fff;border-color:#1a66e0;border-radius:8px}
.i{position:relative;background:#fff;margin:8px 0;padding:10px 44px 10px 14px;border-radius:10px;border-left:6px solid #ccc}
.i.seen{opacity:.55}.green{border-color:#2ecc71}.yellow{border-color:#f1c40f}.red{border-color:#e74c3c}.story{border-color:#7048e8}.story.hot{border-color:#f76707}
.i a{color:#111;text-decoration:none;font-weight:600}.i a:hover{text-decoration:underline}
.new{background:#e03131;color:#fff;font-size:11px;font-weight:700;padding:1px 6px;border-radius:4px;margin-left:6px}
.cnt{background:#f1f3f5;border-radius:999px;padding:1px 8px;font-size:12px;font-weight:700;margin-left:6px}
.hot .cnt{background:#fff4e6;color:#d9480f}
.off{margin-top:6px;font-size:13px}.off a{color:#2b8a3e}.nooff{margin-top:6px;font-size:13px;color:#e8590c}
details{margin-top:6px}summary{cursor:pointer;color:#1a66e0;font-size:13px;font-weight:600}
details ol{margin:6px 0 0;padding-left:20px;font-size:13.5px}details li{margin:3px 0}details li a{font-weight:500}
.x{position:absolute;right:8px;top:8px;border:0;background:#eef2f7;border-radius:6px;width:28px;height:28px;cursor:pointer;font-size:15px}
.x:hover{background:#ffd8d8}.empty{padding:20px;text-align:center;color:#56657a}
</style></head><body>
<div class="top"><div><h2>GovWatch</h2><div class="muted">Ενημερώθηκε: __NOW__ · η σελίδα ανανεώνεται μόνη της κάθε λεπτό</div></div>
<div><button class="act main" id="seenAll">✓ Τα είδα όλα</button> <button class="act" id="restore">Επαναφορά κρυμμένων</button></div></div>
<div class="bar" id="bar"></div><div id="list"></div>
<script>
const RAW = __DATA__;
const TABS = [["new","Νέα"],["hot","🔥 Θέματα"],["official","Επίσημες πηγές"],["syntaxeis","Συντάξεις"],["eforia","Εφορία"],["dei","ΔΕΗ"],["all","Όλα"]];
const ICON = {green:"🟢",yellow:"🟡",red:"🔴"};
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem("gw_" + k)) ?? d; } catch (e) { return d; } },
                set(k, v) { try { localStorage.setItem("gw_" + k, JSON.stringify(v)); } catch (e) {} } };
let hidden = new Set(store.get("hidden", [])), seen = new Set(store.get("seen", [])), tab = store.get("tab", "new");
if (!TABS.some(t => t[0] === tab)) tab = "new";
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const when = ts => `${ts.slice(8,10)}/${ts.slice(5,7)} ${ts.slice(11,16)}`;
// Κάρτες: επίσημες (μία-μία) + θέματα (ομάδες άρθρων)
const CARDS = [
  ...RAW.official.map(d => ({kind: "off", id: d.id, ids: [d.id], d, ts: d.ts, tops: [d.top],
      score: {green: 50, yellow: 20, red: 0}[d.p]})),
  ...RAW.stories.map(st => ({kind: "story", id: st.id, ids: st.items.map(x => x.id), st, ts: st.ts, tops: st.tops,
      score: Math.min(st.n, 60) * 2 + (st.n >= 5 ? 30 : 0)}))
];
const isNew = c => c.ids.some(i => !seen.has(i));
function match(c) {
  if (hidden.has(c.id)) return false;
  // Νέα: επίσημες (όχι κόκκινες) + θέματα που τα γράφουν 2+ site ή έχουν επίσημη πηγή
  if (tab === "new") return isNew(c) && (c.kind === "off" ? c.d.p !== "red" : (c.st.n >= 2 || !!c.st.off));
  if (tab === "hot") return c.kind === "story";
  if (tab === "official") return c.kind === "off";
  if (tab === "all") return true;
  return c.tops.includes(tab);
}
function cardHtml(c) {
  const nw = isNew(c) ? '<span class="new">ΝΕΟ</span>' : "";
  if (c.kind === "off") {
    const d = c.d;
    return `<div class="i ${d.p}${isNew(c) ? "" : " seen"}"><b>${ICON[d.p]} ${esc(d.s)}</b> <small class="muted">${when(d.ts)}</small>${nw}
      <br><a href="${esc(d.u)}" target="_blank" rel="noopener" data-open="${c.id}">${esc(d.t)}</a>
      <button class="x" title="Κρύψε" data-hide="${c.id}">✕</button></div>`;
  }
  const st = c.st, hot = st.n >= 5;
  const offl = st.off ? `<div class="off">✅ Επίσημη πηγή: <a href="${esc(st.off.u)}" target="_blank" rel="noopener">${esc(st.off.s)} — ${esc(st.off.t)}</a></div>`
    : (hot ? '<div class="nooff">⚠️ Δεν βρέθηκε ακόμα επίσημη ανακοίνωση — έλεγξε πριν το ανεβάσεις</div>' : "");
  const list = st.items.map(x => `<li><a href="${esc(x.u)}" target="_blank" rel="noopener" data-open="${c.id}">${esc(x.t)}</a> <small class="muted">${when(x.ts)}</small></li>`).join("");
  return `<div class="i story${hot ? " hot" : ""}${isNew(c) ? "" : " seen"}"><b>${hot ? "🔥" : "📰"} Θέμα</b><span class="cnt">${st.n} ${st.n === 1 ? "άρθρο" : "άρθρα"}</span> <small class="muted">τελευταίο ${when(st.ts)}</small>${nw}
    <br><a href="${esc(st.items[0].u)}" target="_blank" rel="noopener" data-open="${c.id}">${esc(st.t)}</a>${offl}
    ${st.n > 1 ? `<details><summary>Δες όλα τα άρθρα (${st.n})</summary><ol>${list}</ol></details>` : ""}
    <button class="x" title="Κρύψε" data-hide="${c.id}">✕</button></div>`;
}
function render() {
  const cnt = k => CARDS.filter(c => { const t = tab; tab = k; const r = match(c); tab = t; return r; }).length;
  document.getElementById("bar").innerHTML = TABS.map(([k, l]) => `<button class="${k === tab ? "on" : ""}" data-tab="${k}">${l} (${cnt(k)})</button>`).join("");
  const list = CARDS.filter(match).sort((a, b) =>
    (tab === "hot" ? 0 : isNew(b) - isNew(a)) || b.score - a.score || b.ts.localeCompare(a.ts));
  document.getElementById("list").innerHTML = list.length ? list.map(cardHtml).join("") : '<div class="empty">Δεν υπάρχει κάτι εδώ. 👌</div>';
  const n = CARDS.filter(c => { const t = tab; tab = "new"; const r = match(c); tab = t; return r; }).length;
  document.title = (n ? `(${n}) ` : "") + "GovWatch";
}
const byId = id => CARDS.find(c => c.id === id);
const markSeen = c => { c.ids.forEach(i => seen.add(i)); store.set("seen", [...seen]); };
document.addEventListener("click", e => {
  const t = e.target.closest("[data-tab]"); if (t) { tab = t.dataset.tab; store.set("tab", tab); render(); return; }
  const h = e.target.closest("[data-hide]"); if (h) { const c = byId(h.dataset.hide); hidden.add(c.id); store.set("hidden", [...hidden]); markSeen(c); render(); return; }
  const o = e.target.closest("[data-open]"); if (o) { markSeen(byId(o.dataset.open)); setTimeout(render, 50); return; }
  if (e.target.id === "seenAll") { CARDS.forEach(markSeen); render(); }
  if (e.target.id === "restore") { hidden = new Set(); store.set("hidden", []); render(); }
});
render();
// ανανέωση κάθε λεπτό — όχι όσο έχεις ανοιχτή λίστα άρθρων
setInterval(() => { if (!document.querySelector("details[open]")) location.reload(); }, 60000);
</script></body></html>"""
    html = html.replace("__NOW__", datetime.now().strftime("%d/%m/%Y %H:%M")).replace("__DATA__", payload)
    with open(os.path.join(HERE, "notifications.html"), "w", encoding="utf-8") as f:
        f.write(html)


def digest():
    con = db()
    since = (datetime.now() - timedelta(hours=24)).isoformat()
    rows = con.execute("SELECT source,title,url,priority FROM items WHERE first_seen>=? "
                       "ORDER BY priority, source", (since,)).fetchall()
    day = datetime.now().strftime("%d/%m/%Y")
    out = [f"# Σύνοψη ειδοποιήσεων — {day}\n"]
    for p in ("green", "yellow", "red"):
        for s, t, u, pr in rows:
            if pr == p:
                out.append(f"{ICON[p]} **{s}** — {t}\n   {u}\n")
    text = "\n".join(out)
    print(text)
    with open(os.path.join(HERE, f"digest_{datetime.now():%Y-%m-%d}.md"), "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "digest", "telegram", "publish"])
    ap.add_argument("--every", type=int, help="λεπτά ανάμεσα σε ελέγχους")
    ap.add_argument("--fast", type=int, default=15, help="λεπτά για τις πηγές συντάξεων")
    a = ap.parse_args()
    if a.cmd == "telegram":
        tg_setup()
    elif a.cmd == "digest":
        digest()
    elif a.cmd == "publish":
        publish(force=True)
    elif a.every:
        # Όλες οι πηγές κάθε `every` λεπτά, οι πηγές συντάξεων (fast) κάθε `fast` λεπτά
        last_full = 0
        while True:
            if time.time() - last_full >= a.every * 60 - 5:
                run_once()
                last_full = time.time()
            else:
                run_once(only_fast=True)
            for _ in range(min(a.fast, a.every)):
                send_deltio()
                time.sleep(60)
    else:
        run_once()
