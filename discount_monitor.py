"""
Discount Monitor — Παρακολούθηση εκπτώσεων για epidomatatora.gr

Ελέγχει τις επίσημες λίστες συνεργαζόμενων:
  - EYCA (European Youth Card) → europeanyouthcard.gr
  - ΔΥΠΑ (Κάρτα Ανεργίας) → dypa.gov.gr
  - ΟΠΟΤΤΕ (Τρίτεκνοι) → opotte.gr
  - ΑΣΠΕ (Πολύτεκνοι) → aspe.gr

Αποθηκεύει hash κάθε σελίδας. Αν αλλάξει → Telegram alert.
Τρέχει μέσω GitHub Actions κάθε 6 ώρες.
"""

import hashlib
import json
import os
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
HASHES_FILE = os.path.join(HERE, "discount_hashes.json")
DISCOUNTS_JSON = os.path.join(HERE, "site", "discounts.json")

SOURCES = [
    {"id": "eyca_partners", "name": "EYCA — Λίστα Συνεργατών", "url": "https://www.europeanyouthcard.gr/prosfores/", "category": "neoi"},
    {"id": "eyca_main", "name": "EYCA — Κεντρική", "url": "https://www.europeanyouthcard.gr/", "category": "neoi"},
    {"id": "dypa_benefits", "name": "ΔΥΠΑ — Παροχές Ανέργων", "url": "https://www.dypa.gov.gr/paroxes", "category": "anergoi"},
    {"id": "dypa_karta", "name": "ΔΥΠΑ — Κάρτα Ανεργίας", "url": "https://www.dypa.gov.gr/karta-anergias", "category": "anergoi"},
    {"id": "opotte", "name": "ΟΠΟΤΤΕ — Τρίτεκνοι", "url": "https://www.opottte.gr/", "category": "triteknoi"},
    {"id": "aspe", "name": "ΑΣΠΕ — Πολύτεκνοι", "url": "https://www.aspe.gr/", "category": "polyteknoi"},
    {"id": "isic_gr", "name": "ISIC Greece — Φοιτητικές Εκπτώσεις", "url": "https://www.isic.gr/", "category": "foitites"},
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DiscountMonitor/1.0; epidomatatora.gr)"}


def tg_config():
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


def notify(text):
    token, chat = tg_config()
    if not (token and chat):
        print("Telegram not configured")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text, "parse_mode": "HTML"}, timeout=20)
        return r.ok
    except requests.RequestException as e:
        print(f"Telegram error: {e}")
        return False


def load_hashes():
    if os.path.exists(HASHES_FILE):
        with open(HASHES_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_hashes(hashes):
    with open(HASHES_FILE, "w", encoding="utf-8") as f:
        json.dump(hashes, f, indent=2, ensure_ascii=False)


def fetch_page(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def check_sources():
    hashes = load_hashes()
    changes = []
    for src in SOURCES:
        sid = src["id"]
        print(f"  Checking {src['name']}...")
        text = fetch_page(src["url"])
        if text is None:
            continue
        new_hash = content_hash(text)
        old_hash = hashes.get(sid)
        if old_hash is None:
            print("    First scan, saving hash")
            hashes[sid] = new_hash
        elif old_hash != new_hash:
            print("    CHANGE DETECTED!")
            changes.append(src)
            hashes[sid] = new_hash
        else:
            print("    No change")
    save_hashes(hashes)
    return changes


def run():
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    print(f"Discount Monitor — {now}")
    print(f"  Checking {len(SOURCES)} sources...")
    changes = check_sources()
    if not changes:
        print("  No changes detected")
        return
    lines = ["<b>Discount Monitor — Αλλαγές!</b>\n"]
    for c in changes:
        lines.append(f"• <b>{c['name']}</b>")
        lines.append(f"  {c['url']}")
        lines.append(f"  Κατηγορία: {c['category']}")
        lines.append("")
    lines.append(f"⏰ {now}")
    lines.append("👉 Έλεγξε τις αλλαγές και ενημέρωσε το discounts.json αν χρειάζεται")
    msg = "\n".join(lines)
    print("  Sending Telegram alert...")
    notify(msg)
    print(f"  Alert sent for {len(changes)} change(s)")


if __name__ == "__main__":
    run()
