"""Κοινή βάση registry.db + κοινά εργαλεία για τα bots Προθεσμιών / Αλλαγών / Πληρωμών.
Δεν αγγίζει το monitor.py ούτε γράφει στο seen.db (μόνο διαβάζει)."""
import os, re, sqlite3, unicodedata, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "registry.db")
SEEN = os.path.join(HERE, "seen.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS topics(
  key TEXT PRIMARY KEY, title TEXT, first_seen TEXT, last_seen TEXT,
  n_items INTEGER, n_sources INTEGER, url TEXT);
CREATE TABLE IF NOT EXISTS deadlines(
  id INTEGER PRIMARY KEY AUTOINCREMENT, benefit TEXT, deadline_date TEXT,
  title TEXT, url TEXT, source TEXT, first_seen TEXT,
  stage INTEGER DEFAULT 0, UNIQUE(benefit, deadline_date));
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, benefit TEXT, pay_date TEXT,
  title TEXT, url TEXT, source TEXT, first_seen TEXT,
  stage INTEGER DEFAULT 0, UNIQUE(benefit, pay_date));
CREATE TABLE IF NOT EXISTS changes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, page_url TEXT, name TEXT,
  old_hash TEXT, new_hash TEXT, detected TEXT, notified INTEGER DEFAULT 0);
"""


def connect(path=REGISTRY):
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    return c


def seen_conn(path=SEEN):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def get_meta(c, k, default=None):
    r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def set_meta(c, k, v):
    c.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


def norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.replace("ς", "σ")


def clean_title(t):
    """Αφαιρεί την κατάληξη « - Όνομα Site» που βάζει το Google News."""
    return re.sub(r"(\s+[-–|]\s+[^-–|]{2,40}){1,2}$", "", t or "").strip()


MONTHS = {"ιανουαρ": 1, "φεβρουαρ": 2, "μαρτ": 3, "απριλ": 4, "μαιου": 5, "μαϊου": 5, "μαι": 5,
          "ιουν": 6, "ιουλ": 7, "αυγουστ": 8, "σεπτεμβρ": 9, "οκτωβρ": 10, "νοεμβρ": 11, "δεκεμβρ": 12}
_MSTEMS = "|".join(sorted((norm(k) for k in MONTHS), key=len, reverse=True))
RE_DAY_MONTH = re.compile(r"\b(\d{1,2})\s*(?:η|ης)?\s+(" + _MSTEMS + r")\w*\.?(?:\s+(20\d\d))?")
RE_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_MAP = {norm(k): v for k, v in MONTHS.items()}


def _month(stem):
    for k, v in _MAP.items():
        if stem.startswith(k):
            return v
    return None


def find_dates(text, ref):
    """Επιστρέφει λίστα (date, start_pos) από ελληνικό κείμενο. ref: ημερομηνία αναφοράς (για το έτος)."""
    t = norm(text)
    out = []
    cand = []
    for m in RE_DAY_MONTH.finditer(t):
        cand.append((int(m.group(1)), _month(m.group(2)), m.group(3), m.start()))
    for m in RE_SLASH.finditer(t):
        y = m.group(3)
        if y and len(y) == 2:
            y = "20" + y
        cand.append((int(m.group(1)), int(m.group(2)), y, m.start()))
    for d, mo, y, pos in cand:
        if not mo or not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        year = int(y) if y else ref.year
        try:
            day = dt.date(year, mo, d)
        except ValueError:
            continue
        if not y and day < ref - dt.timedelta(days=30):
            try:
                day = dt.date(year + 1, mo, d)
            except ValueError:
                continue
        out.append((day, pos))
    return out


BENEFIT_WORDS = re.compile(r"επιδομ|συνταξ|ενισχυσ|επιστροφ|αποζημιω|βοηθημα|voucher|κουπον|market pass|μερισμα|ελαφρυνσ|bonus|μπονους")
RE_BENEFIT_NAME = re.compile(r"(επιδομα\s+[α-ωa-z0-9]+(?:\s+[α-ωa-z0-9]+)?|συνταξ\w+|ενισχυση\s+[α-ωa-z0-9]+|επιστροφη\s+[α-ωa-z0-9]+|κοινωνικο μερισμα|market pass)")
STOP = {"των", "του", "της", "και", "για", "στο", "στη", "με", "απο", "το", "τα", "τη", "την", "τον", "στις", "στους", "στισ", "στουσ", "που", "στην", "νεα"}


def benefit_name(title):
    m = RE_BENEFIT_NAME.search(norm(clean_title(title)))
    if not m:
        return "γενικά"
    words = [w for w in m.group(1).split() if w not in STOP]
    return " ".join(words[:3])


def tokens(title):
    return {w for w in re.findall(r"[α-ωa-z0-9]{4,}", norm(clean_title(title)))}


def similarity(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


# ---------- Telegram (ξεχωριστό κανάλι, ΟΧΙ το κύριο του GovWatch) ----------
def tg_config():
    token, chat = os.getenv("REGISTRY_TELEGRAM_TOKEN"), os.getenv("REGISTRY_TELEGRAM_CHAT_ID")
    path = os.path.join(HERE, "telegram_registry.txt")
    if os.path.exists(path):
        lines = [l.strip() for l in open(path, encoding="utf-8").read().splitlines() if l.strip()]
        if lines:
            token = lines[0]
        if len(lines) > 1:
            chat = lines[1]
    return token, chat


def send_telegram(text):
    """True αν στάλθηκε. Αν δεν υπάρχει ρύθμιση καναλιού, επιστρέφει False (τίποτα δεν χάνεται)."""
    token, chat = tg_config()
    if not token or not chat:
        print("[registry] Δεν υπάρχει κανάλι Telegram — δεν στάλθηκε:\n" + text)
        return False
    import requests
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"}, timeout=20)
        return r.status_code == 200
    except Exception as e:
        print("[registry] Σφάλμα Telegram:", e)
        return False


def today():
    return dt.date.today()


# ---------- Κοινή λογική για Bot Προθεσμιών & Bot Πληρωμών ----------
def scan_and_notify(table, datecol, emoji, label, kw_re, near_kw=None, exclude_near=None, now=None, seen_path=SEEN, reg=None, send=send_telegram):
    """Διαβάζει νέα items από το seen.db, εξάγει ημερομηνίες, γράφει στο registry και ειδοποιεί.
    near_kw: αν δοθεί, η ημερομηνία πρέπει να είναι ≤60 χαρακτήρες μετά από αυτή τη λέξη-κλειδί."""
    import dedupe
    now = now or dt.datetime.now()
    reg = reg or connect()
    cur_key = f"cursor_{table}"
    cursor = get_meta(reg, cur_key)
    s = seen_conn(seen_path)
    q, args = "SELECT source, title, url, first_seen FROM items", ()
    if cursor:
        q += " WHERE first_seen > ?"; args = (cursor,)
    rows = s.execute(q + " ORDER BY first_seen", args).fetchall()
    s.close()
    fresh_limit = (now - dt.timedelta(days=2)).isoformat()
    added = 0
    for source, title, url, fs in rows:
        nt = norm(title)
        if not (kw_re.search(nt) and BENEFIT_WORDS.search(nt)):
            continue
        ref = dt.datetime.fromisoformat(fs[:19]).date() if fs and fs[:4] > "2000" else now.date()
        pick = None
        for day, pos in find_dates(title, ref):
            if exclude_near and any(0 <= pos - m2.end() <= 25 for m2 in exclude_near.finditer(nt)):
                continue
            if near_kw:
                m = None
                for m in near_kw.finditer(nt):
                    if 0 <= pos - m.end() <= 60:
                        pick = day; break
                if pick: break
            else:
                pick = day; break
        if not pick or pick < now.date() - dt.timedelta(days=1) or pick > now.date() + dt.timedelta(days=400):
            continue
        stage = 0 if fs >= fresh_limit else 1
        # ίδιο γεγονός (ίδια μέρα, παρόμοιος τίτλος) από άλλο site/άλλη ονομασία = διπλότυπο
        if any(similarity(title, r[0]) >= 0.4 for r in
               reg.execute(f"SELECT title FROM {table} WHERE {datecol}=?", (pick.isoformat(),))):
            continue
        cur = reg.execute(f"INSERT OR IGNORE INTO {table}(benefit,{datecol},title,url,source,first_seen,stage) VALUES(?,?,?,?,?,?,?)",
                          (benefit_name(title), pick.isoformat(), clean_title(title), url, source, fs, stage))
        added += cur.rowcount
    if rows:
        set_meta(reg, cur_key, rows[-1][3])
    reg.commit()

    # 1) νέες ειδοποιήσεις (ένα μήνυμα, ομαδοποιημένες χωρίς διπλότυπα)
    new = reg.execute(f"SELECT id,benefit,{datecol},title,url FROM {table} WHERE stage=0 ORDER BY {datecol}").fetchall()
    new_u = dedupe.dedupe_items([(r[3],) + r for r in new])
    sent = 0
    if new_u:
        lines = [f"{emoji} {label} — νέα" ]
        for r in new_u[:10]:
            d = dt.date.fromisoformat(r[3])
            lines.append(f"• {d.strftime('%d/%m/%Y')} — {r[4]}\n  {r[5]}")
        if send("\n".join(lines)):
            reg.execute(f"UPDATE {table} SET stage=1 WHERE stage=0")
            sent += len(new_u)
    # 2) υπενθυμίσεις 3 ημερών / 1 ημέρας
    for days, need, setto, tag in ((3, 2, 2, "σε 3 ημέρες"), (1, 3, 3, "αύριο/σήμερα")):
        lim = (now.date() + dt.timedelta(days=days)).isoformat()
        due = reg.execute(f"SELECT id,benefit,{datecol},title,url FROM {table} WHERE stage>=1 AND stage<? AND {datecol}<=? AND {datecol}>=?",
                          (setto, lim, (now.date()).isoformat())).fetchall()
        if due:
            lines = [f"⏰ {label} — {tag}"] + [f"• {dt.date.fromisoformat(r[2]).strftime('%d/%m/%Y')} — {r[1]}\n  {r[4]}" for r in due[:10]]
            if send("\n".join(lines)):
                ids = ",".join(str(r[0]) for r in due)
                reg.execute(f"UPDATE {table} SET stage=? WHERE id IN ({ids})", (setto,))
                sent += len(due)
    reg.commit()
    return added, sent
