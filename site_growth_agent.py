#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent 2 — Site Growth Agent (v2 — διορθωμένη έκδοση μετά από έλεγχο)

Σκοπός: να «μεγαλώνει» μόνο του το epidomatatora.gr, χωρίς χειροκίνητη δουλειά.

Τι κάνει σε κάθε εκτέλεση:
  1. Διαβάζει το site/anakoinoseis.json (τις ήδη επαληθευμένες ανακοινώσεις του GovWatch).
  2. Ομαδοποιεί τις ανακοινώσεις σε «θεματικούς κόμβους» (π.χ. Πληρωμές ΔΥΠΑ/e-ΕΦΚΑ,
     Συντάξεις, Επίδομα Παιδιού Α21, Ρυθμίσεις οφειλών) με ΑΥΣΤΗΡΟ φιλτράρισμα στον
     ΤΙΤΛΟ (βλ. match_theme), όχι σε ολόκληρο το κείμενο.
  3. Φτιάχνει/ανανεώνει μία SEO landing page ανά θέμα, που απλώς παραθέτει (όχι εφευρίσκει)
     τις πραγματικές, ήδη ελεγμένες ανακοινώσεις.
  4. Πριν αλλάξει μια υπάρχουσα σελίδα, κρατάει αντίγραφο ασφαλείας σε agent2_backups/
     (εκτός site/, άρα ΔΕΝ δημοσιεύεται ποτέ).
  5. Ενημερώνει το manual.json — ΜΟΝΟ τις 4 δικές του εγγραφές (ποτέ άλλη ανακοίνωση).
  6. Καλεί monitor.py publish και ΕΠΙΒΕΒΑΙΩΝΕΙ πραγματικό deploy πριν δηλώσει επιτυχία
     (βλ. deploy()) — δεν εμπιστεύεται μόνο τον exit code, γιατί το monitor.py πάντα
     επιστρέφει 0.
  7. Γράφει ποια ΔΙΚΑ ΤΟΥ αρχεία άλλαξε σε .agent2_changed_files.txt, ώστε το git add
     στο workflow να περιορίζεται σε αυτά — ποτέ `git add -A`.
  8. Γράφει σύντομη αναφορά στο site_growth_log.md και (αν υπάρχει email.txt) στέλνει
     καθημερινή αναφορά με EMAIL (όχι Telegram — βλ. notify_email). Τα 20 υπάρχοντα
     Telegram bots του GovWatch δεν αγγίζονται καθόλου από αυτό το αρχείο.

Σχεδιασμένο να τρέχει μόνο του, 1 φορά τη μέρα, μέσα από GitHub Actions
(.github/workflows/site-growth-agent.yml).
"""
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
MANUAL = os.path.join(HERE, "manual.json")
FEED = os.path.join(SITE, "anakoinoseis.json")
LOG = os.path.join(HERE, "site_growth_log.md")
BACKUPS = os.path.join(HERE, "agent2_backups")   # ΕΚΤΟΣ site/ — ποτέ δεν δημοσιεύεται
CHANGED_FILES_MANIFEST = os.path.join(HERE, ".agent2_changed_files.txt")
SITE_URL = "https://epidomatatora.gr"

MAX_ITEMS_PER_PAGE = 30
MIN_ITEMS_TO_PUBLISH = 2   # κάτω από αυτό δεν αξίζει ακόμη δική του σελίδα

# ---------------------------------------------------------------------------
# Λέξεις/φράσεις που αποκλείουν ΑΜΕΣΩΣ μια ανακοίνωση, όποιο θέμα κι αν ταιριάζει
# «τυχαία» (κληρώσεις επιτροπών, σχολικά γεύματα, κ.λπ. — βλ. test_site_growth_agent.py)
# ---------------------------------------------------------------------------
EXCLUDE_PATTERNS = [
    "κληρωσ",            # κληρώσεις επιτροπών/διαγωνισμών — άσχετο με επιδόματα
    "σχολικ γευμ",        # πρόγραμμα σχολικών γευμάτων
    "αντιπλημμυρικ",      # έργα ΕΣΠΑ κ.ά. γενικά νέα υποδομών
]

# ---------------------------------------------------------------------------
# Θεματικοί κόμβοι: κάθε ένας γίνεται μία SEO σελίδα.
#
# Λογική ταιριάσματος (βλ. match_theme): ΜΟΝΟ στον τίτλο (όχι στο ελεύθερο κείμενο,
# που έβαζε μέσα άσχετες ανακοινώσεις). Ένα θέμα «περνάει» αν:
#   (α) ο τίτλος περιέχει μία ΕΙΔΙΚΗ/μη διφορούμενη φράση (strong_title) — αρκεί μόνη
#       της, ακόμη κι αν δεν αναφέρεται φορέας (π.χ. "Α21", "συνταξ", "120 δοσ"), ή
#   (β) ο τίτλος περιέχει ΤΑΥΤΟΧΡΟΝΑ έναν σχετικό φορέα (agency_terms) ΚΑΙ έναν
#       όρο-θέμα (topic_terms) — συνδυασμός, όχι μία μόνη γενική λέξη.
# ---------------------------------------------------------------------------
THEMES = [
    {
        "slug": "pliromes-dypa-efka",
        "cat": "pliromes",
        "nav": "Πληρωμές ΔΥΠΑ & e-ΕΦΚΑ",
        "h1": "Πληρωμές ΔΥΠΑ & e-ΕΦΚΑ — Ημερολόγιο Πληρωμών",
        "desc": "Όλες οι ανακοινωμένες πληρωμές ΔΥΠΑ και e-ΕΦΚΑ (επιδόματα, παροχές, επιστροφές), με ημερομηνία και επίσημη πηγή. Ενημερώνεται αυτόματα.",
        "strong_title": [],  # καμία αφ' εαυτής αρκετή — πάντα θέλει τον συνδυασμό (β)
        "agency_terms": ["δυπα", "εφκα"],
        "topic_terms": ["πληρωμ", "λογαριασμ", "καταβολ", "καταβαλ"],
    },
    {
        "slug": "syntaxeis-pliromes",
        "cat": "syntaxeis",
        "nav": "Συντάξεις — Ημερομηνίες Πληρωμών",
        "h1": "Συντάξεις: Ημερομηνίες Πληρωμών",
        "desc": "Ανακοινώσεις e-ΕΦΚΑ για το πότε πληρώνονται οι συντάξεις κάθε μήνα, με επίσημη πηγή. Ενημερώνεται αυτόματα.",
        "strong_title": ["συνταξ"],  # αρκεί μόνη της — αδιαμφισβήτητα το θέμα, ακόμη κι αν λείπει «e-ΕΦΚΑ» από τον τίτλο
        "agency_terms": ["εφκα"],
        "topic_terms": ["πληρωμ", "ημερομην"],
    },
    {
        "slug": "epidoma-paidiou-a21",
        "cat": "paroxes",
        "nav": "Επίδομα Παιδιού (Α21)",
        "h1": "Επίδομα Παιδιού Α21 — Νέα & Ανακοινώσεις",
        "desc": "Όλες οι επίσημες ανακοινώσεις ΟΠΕΚΑ για το Επίδομα Παιδιού Α21: αιτήσεις, πληρωμές, προθεσμίες. Ενημερώνεται αυτόματα.",
        "strong_title": ["α21", "επιδομα παιδιου"],
        "agency_terms": ["οπεκα"],
        "topic_terms": ["αιτησ", "πληρωμ", "προθεσμ"],
    },
    {
        "slug": "rythmisi-ofeilon",
        "cat": "forologia",
        "nav": "Ρύθμιση Οφειλών (Εφορία / Ταμεία)",
        "h1": "Ρύθμιση Οφειλών σε Εφορία & Ασφαλιστικά Ταμεία",
        "desc": "Ανακοινώσεις για ρυθμίσεις χρεών (δόσεις) σε Εφορία, e-ΕΦΚΑ και ασφαλιστικά ταμεία, με επίσημη πηγή. Ενημερώνεται αυτόματα.",
        # «120 δόσεις» / «72 δόσεις» είναι συγκεκριμένο, αναγνωρίσιμο πρόγραμμα — αρκεί μόνο
        # του, ακόμη κι αν ο τίτλος (π.χ. δήλωση υπουργού) δεν επαναλαμβάνει «Εφορία».
        "strong_title": ["120 δοσ", "72 δοσ", "ρυθμιση οφειλων"],
        "agency_terms": ["εφορια", "αααδε", "ασφαλιστικ", "myaade"],
        "topic_terms": ["ρυθμισ", "δοσεις", "δοσεων", "οφειλ"],
    },
]

# Το ΜΟΝΑΔΙΚΟ σύνολο URLs που επιτρέπεται στον Agent 2 να δημιουργήσει/αλλάξει μέσα
# στο manual.json — καμία άλλη εγγραφή (χειροκίνητη ή άλλου bot) δεν αγγίζεται ποτέ.
AGENT2_URLS = {f"/{t['slug']}.html" for t in THEMES}


def norm(s):
    """Μικρά γράμματα, χωρίς τόνους — για ασφαλές ταίριασμα λέξεων-κλειδιών."""
    s = s or ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()


def load_feed():
    if not os.path.exists(FEED):
        return []
    with open(FEED, encoding="utf-8") as f:
        return json.load(f)


def load_manual():
    if not os.path.exists(MANUAL):
        return []
    with open(MANUAL, encoding="utf-8") as f:
        return json.load(f)


def save_manual(items):
    with open(MANUAL, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
        f.write("\n")


def _words(title):
    """Λέξεις του τίτλου (ήδη normalized), χωρίς σημεία στίξης."""
    return re.findall(r"[a-zα-ω0-9]+", title)


def _term_matches(term, title, words):
    """Ένας όρος ταιριάζει είτε ως ΑΡΧΗ μιας ολόκληρης λέξης (π.χ. 'πληρωμ' ταιριάζει
    στο 'πληρωμών' αλλά ΟΧΙ μέσα στο 'συμπληρωματική' — stem, όχι τυχαίο substring),
    είτε, για πολυλεκτικές φράσεις (έχουν κενό, π.χ. '120 δοσ'), ως substring σε
    ολόκληρο τον τίτλο."""
    if " " in term:
        return term in title
    return any(w.startswith(term) for w in words)


def match_theme(item, theme):
    """Αυστηρό ταίριασμα — ΜΟΝΟ στον τίτλο (όχι στο ελεύθερο κείμενο).

    Περνάει αν:
      (α) ο τίτλος περιέχει μία ειδική φράση (strong_title) — αρκεί μόνη της, ή
      (β) ο τίτλος περιέχει ΚΑΙ φορέα (agency_terms) ΚΑΙ όρο-θέμα (topic_terms).
    Κάθε όρος ταιριάζει μόνο ως αρχή λέξης (βλ. _term_matches), ώστε λέξεις όπως
    «ΣΥΜπληρωματική» να ΜΗΝ ενεργοποιούν το keyword «πληρωμ».
    Πρώτα ελέγχονται τα EXCLUDE_PATTERNS — αν ταιριάξουν, απορρίπτεται αμέσως,
    ό,τι κι αν λέει το υπόλοιπο.
    """
    title = norm(item.get("title") or "")
    words = _words(title)

    if any(_term_matches(bad, title, words) for bad in EXCLUDE_PATTERNS):
        return False

    if any(_term_matches(phrase, title, words) for phrase in theme["strong_title"]):
        return True

    has_agency = any(_term_matches(a, title, words) for a in theme["agency_terms"])
    has_topic = any(_term_matches(t, title, words) for t in theme["topic_terms"])
    return has_agency and has_topic


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build_page_html(theme, items):
    url = f"{SITE_URL}/{theme['slug']}.html"
    updated = datetime.now().strftime("%d/%m/%Y")
    rows = []
    for it in items[:MAX_ITEMS_PER_PAGE]:
        date = esc(it.get("date", ""))
        title = esc(it.get("title", ""))
        foreas = esc(it.get("foreas", ""))
        link = esc(it.get("url", "#"))
        text = esc((it.get("text") or "")[:220])
        external = link.startswith("http")
        rel = ' rel="nofollow noopener" target="_blank"' if external else ""
        rows.append(f"""
      <li class="item">
        <span class="date">{date}</span>
        <a class="title" href="{link}"{rel}>{title}</a>
        <span class="foreas">{foreas}</span>
        <p class="snippet">{text}</p>
      </li>""")
    items_html = "\n".join(rows) if rows else "<li class=\"item\">Δεν υπάρχουν ακόμη καταχωρημένες ανακοινώσεις για αυτό το θέμα.</li>"

    faq_jsonld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": f"Πώς ενημερώνεται η σελίδα «{theme['nav']}»;",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Η σελίδα ενημερώνεται αυτόματα κάθε φορά που εντοπίζεται νέα επίσημη ανακοίνωση σχετική με το θέμα, μέσα από το σύστημα παρακολούθησης GovWatch του Επιδόματα Τώρα."
                },
            },
            {
                "@type": "Question",
                "name": "Οι πληροφορίες είναι επίσημες;",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Κάθε εγγραφή παραπέμπει στην αρχική επίσημη πηγή (ΔΥΠΑ, e-ΕΦΚΑ, ΟΠΕΚΑ, Υπουργεία κ.ά.). Το Επιδόματα Τώρα συγκεντρώνει και δεν τροποποιεί το περιεχόμενο των ανακοινώσεων."
                },
            },
        ],
    }

    return f"""<!doctype html>
<html lang="el">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(theme['h1'])} · Επιδόματα Τώρα</title>
<meta name="description" content="{esc(theme['desc'])}">
<link rel="canonical" href="{url}">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#0d2b52">
<meta property="og:type" content="article">
<meta property="og:locale" content="el_GR">
<meta property="og:site_name" content="Επιδόματα Τώρα">
<meta property="og:title" content="{esc(theme['h1'])}">
<meta property="og:description" content="{esc(theme['desc'])}">
<meta property="og:url" content="{url}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Commissioner:wght@400;500;600;700&family=Literata:opsz,wght@7..72,600;7..72,700&display=swap">
<script type="application/ld+json">{json.dumps(faq_jsonld, ensure_ascii=False)}</script>
<style>
:root {{
  --bg:#f4f6f9; --surface:#fff; --tint:#eef3fa; --navy:#0d2b52; --blue:#1a66e0;
  --blue-soft:#e3edfc; --ink:#14202e; --muted:#56657a; --line:#dde4ed;
  --sans:"Commissioner","Segoe UI",Arial,sans-serif; --serif:"Literata",Georgia,serif;
  --wrap:860px; --r:10px;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:400 16px/1.6 var(--sans); }}
a {{ color:var(--blue); text-underline-offset:2px; }}
.wrap {{ max-width:var(--wrap); margin:0 auto; padding:0 20px; }}
header.top {{ background:var(--navy); color:#fff; padding:14px 0; }}
header.top .wrap {{ display:flex; align-items:center; justify-content:space-between; }}
header.top a.brand {{ color:#fff; text-decoration:none; font:700 18px var(--serif); }}
header.top a.back {{ color:#c9d6e8; text-decoration:none; font-size:14px; font-weight:600; }}
main {{ padding:36px 0 60px; }}
h1 {{ font-family:var(--serif); color:var(--navy); font-size:clamp(26px,4vw,36px); line-height:1.2; margin:0 0 10px; }}
.lede {{ color:var(--muted); font-size:16px; margin:0 0 6px; }}
.updated {{ color:var(--muted); font-size:13px; margin:0 0 28px; }}
ul.items {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:14px; }}
.item {{ background:var(--surface); border:1px solid var(--line); border-radius:var(--r); padding:16px 18px; }}
.item .date {{ display:inline-block; font-size:12.5px; font-weight:700; color:var(--blue); background:var(--blue-soft); padding:2px 9px; border-radius:20px; margin-bottom:6px; }}
.item .title {{ display:block; font-weight:700; color:var(--navy); text-decoration:none; font-size:16.5px; margin:2px 0 4px; }}
.item .title:hover {{ text-decoration:underline; }}
.item .foreas {{ display:block; font-size:12.5px; color:var(--muted); font-weight:600; margin-bottom:6px; }}
.item .snippet {{ margin:0; color:var(--muted); font-size:14.5px; }}
footer {{ padding:24px 0 50px; text-align:center; color:var(--muted); font-size:13px; }}
footer a {{ color:var(--muted); }}
</style>
</head>
<body>
<header class="top">
  <div class="wrap">
    <a class="brand" href="/">Επιδόματα Τώρα</a>
    <a class="back" href="/">← Όλες οι ανακοινώσεις</a>
  </div>
</header>
<main>
  <div class="wrap">
    <h1>{esc(theme['h1'])}</h1>
    <p class="lede">{esc(theme['desc'])}</p>
    <p class="updated">Τελευταία ενημέρωση: {updated} · {len(items)} ανακοινώσεις</p>
    <ul class="items">{items_html}
    </ul>
  </div>
</main>
<footer>
  <div class="wrap">Πηγή κάθε ανακοίνωσης αναγράφεται στον σύνδεσμο. · <a href="/">epidomatatora.gr</a></div>
</footer>
</body>
</html>
"""


def backup_page(slug):
    """Αντίγραφο ασφαλείας ΠΡΙΝ αλλάξει μια υπάρχουσα σελίδα — σε φάκελο ΕΚΤΟΣ site/,
    ώστε να μην δημοσιεύεται ποτέ κατά λάθος στο live site."""
    path = os.path.join(SITE, f"{slug}.html")
    if not os.path.exists(path):
        return None
    os.makedirs(BACKUPS, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = os.path.join(BACKUPS, f"{slug}.{ts}.html")
    with open(path, encoding="utf-8") as src, open(backup_path, "w", encoding="utf-8") as dst:
        dst.write(src.read())
    return backup_path


def upsert_manual(theme, n_items):
    """Προσθέτει/ενημερώνει ΜΟΝΟ τη δική του εγγραφή (url στο AGENT2_URLS).
    Ποτέ δεν αγγίζει εγγραφή που δεν του ανήκει."""
    url = f"/{theme['slug']}.html"
    assert url in AGENT2_URLS, f"BUG: ο Agent 2 προσπάθησε να γράψει URL εκτός του δικού του scope: {url}"

    items = load_manual()
    today = datetime.now().strftime("%Y-%m-%d")
    entry = {
        "date": today,
        "foreas": "Επιδόματα Τώρα",
        "title": theme["h1"],
        "url": url,
        "text": theme["desc"] + f" ({n_items} ανακοινώσεις ως τώρα.)",
        "auto": False,
        "top": False,
        "cat": theme["cat"],
    }
    for i, it in enumerate(items):
        if it.get("url") == url:
            items[i] = entry
            save_manual(items)
            return "updated"
    items.insert(0, entry)
    save_manual(items)
    return "created"


def run():
    feed = load_feed()
    # Εξαίρεση των ΔΙΚΩΝ ΤΟΥ σελίδων από τα υποψήφια items: αλλιώς, από τη στιγμή που
    # μια θεματική σελίδα μπει στο manual.json (άρα και στο anakoinoseis.json), ο
    # επόμενος κύκλος θα την έβρισκε ξανά ως «ανακοίνωση» και θα αυτο-αναφερόταν
    # (ή, χειρότερα, θα «μόλυνε» ΑΛΛΟ θέμα — π.χ. ο τίτλος της σελίδας ΔΥΠΑ περιέχει
    # «ΕΦΚΑ»+«Πληρωμών» και ταίριαζε λανθασμένα και στη σελίδα Συντάξεων).
    feed = [it for it in feed if it.get("url") not in AGENT2_URLS]
    if not feed:
        print("[!] Δεν βρέθηκε/άδειο το site/anakoinoseis.json — τίποτα να επεξεργαστώ.")
        return [], []

    report_lines = [f"## Agent 2 — Site Growth · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"]
    touched = []
    changed_files = set()

    for theme in THEMES:
        matches = [it for it in feed if match_theme(it, theme)]
        matches.sort(key=lambda it: it.get("date", ""), reverse=True)
        if len(matches) < MIN_ITEMS_TO_PUBLISH:
            continue

        existed = os.path.exists(os.path.join(SITE, f"{theme['slug']}.html"))
        if existed:
            backup_page(theme["slug"])  # ασφάλεια πριν την αλλαγή

        html = build_page_html(theme, matches)
        path = os.path.join(SITE, f"{theme['slug']}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        changed_files.add(os.path.relpath(path, HERE))

        action = upsert_manual(theme, len(matches))
        changed_files.add(os.path.relpath(MANUAL, HERE))

        touched.append((theme, len(matches), action))
        verb = "Ανανεώθηκε" if existed else "✨ Δημιουργήθηκε νέα σελίδα"
        report_lines.append(f"- {verb}: **{theme['nav']}** — {len(matches)} ανακοινώσεις — /{theme['slug']}.html")

    if not touched:
        report_lines.append("- Καμία αλλαγή (δεν υπήρχαν αρκετές έγκυρες ανακοινώσεις ανά θέμα).")

    report = "\n".join(report_lines) + "\n"
    print(report)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("\n" + report)
    changed_files.add(os.path.relpath(LOG, HERE))

    return touched, sorted(changed_files)


DEFAULT_REPORT_TO = "epidomatatora.reports@gmail.com"


def build_email_report(touched, deploy_ok, backend, error_detail=None):
    """Φτιάχνει (subject, body) για την καθημερινή αναφορά — ΧΩΡΙΣ δίκτυο, άρα
    ελέγχεται πλήρως με δοκιμές (βλ. test_site_growth_agent.py). Καλύπτει τα 5
    σημεία που ζητήθηκαν: περιεχόμενο, SEO, δημοσίευση/αποτυχία, προβλήματα,
    μετρήσεις Google.
    """
    today = datetime.now().strftime("%d/%m/%Y")
    status_word = "ΕΠΙΤΥΧΙΑ" if deploy_ok else "ΠΡΟΒΛΗΜΑ"
    subject = f"[Agent 2 — Site Growth] Καθημερινή αναφορά {today} — {status_word}"

    lines = [f"Αναφορά Agent 2 (Site Growth) — {today}", ""]

    lines.append("1) Περιεχόμενο που δημιουργήθηκε/ενημερώθηκε:")
    if touched:
        for theme, n, action in touched:
            verb = "✨ νέα σελίδα" if action == "created" else "↻ ανανεώθηκε"
            lines.append(f"   • {theme['nav']} — {verb} ({n} ανακοινώσεις) — /{theme['slug']}.html")
    else:
        lines.append("   • Καμία αλλαγή σήμερα (δεν υπήρχαν αρκετές νέες έγκυρες ανακοινώσεις ανά θέμα).")

    lines.append("")
    lines.append("2) Αλλαγές SEO:")
    if touched:
        lines.append("   Για κάθε σελίδα που άλλαξε, ενημερώθηκαν αυτόματα: τίτλος, meta description,")
        lines.append("   canonical link, Open Graph tags, και JSON-LD δομημένα δεδομένα (FAQPage).")
    else:
        lines.append("   Καμία — δεν άλλαξε/δημιουργήθηκε σελίδα σήμερα.")

    lines.append("")
    lines.append("3) Δημοσίευση:")
    if not touched:
        lines.append("   — Δεν έγινε προσπάθεια deploy (δεν υπήρχε καμία αλλαγή να δημοσιευτεί).")
    elif deploy_ok:
        lines.append(f"   ✅ Το deploy επιβεβαιώθηκε πραγματικά (backend: {backend}).")
    else:
        lines.append(f"   ❌ ΑΠΕΤΥΧΕ το deploy (backend: {backend}). Οι αλλαγές ΔΕΝ ανέβηκαν live.")

    lines.append("")
    lines.append("4) Προβλήματα & ενέργειες που χρειάζονται:")
    if error_detail:
        lines.append(f"   ⚠️ {error_detail[:1000]}")
        lines.append("   Ενέργεια: έλεγξε το GitHub Actions run του Agent 2 πριν ξανατρέξει.")
    else:
        lines.append("   Κανένα πρόβλημα σήμερα.")

    lines.append("")
    lines.append("5) Μετρήσεις Google (Search Console / Analytics):")
    lines.append("   Δεν υπάρχει ακόμη σύνδεση με Google Search Console/Analytics σε αυτό το")
    lines.append("   σύστημα — το πεδίο αυτό θα παραμείνει κενό (όχι εφευρημένοι αριθμοί) μέχρι")
    lines.append("   να συνδεθεί πραγματική πηγή δεδομένων.")

    return subject, "\n".join(lines) + "\n"


def notify_email(touched, deploy_ok, backend, error_detail=None):
    """Στέλνει την καθημερινή αναφορά με EMAIL (αντί για Telegram), μέσω Gmail SMTP.

    Credentials από email.txt (ΙΔΙΟ μοτίβο με telegram.txt/cloudflare.txt — δεν
    υπάρχει άλλη έτοιμη λειτουργία email σε αυτό το repo για να επαναχρησιμοποιηθεί,
    βλ. αναφορά): γραμμή 1 = διεύθυνση αποστολέα/λογαριασμού, γραμμή 2 = Gmail App
    Password, προαιρετική γραμμή 3 = παραλήπτης (αν λείπει, στέλνεται στην ίδια
    διεύθυνση — epidomatatora.reports@gmail.com).

    ΔΕΝ αγγίζει telegram.txt ούτε τα 20 υπάρχοντα Telegram bots του GovWatch.
    """
    path = os.path.join(HERE, "email.txt")
    if not os.path.exists(path):
        print("[!] Δεν βρέθηκε email.txt — η αναφορά ΔΕΝ στάλθηκε με email (μόνο στο log).")
        return False

    with open(path, encoding="utf-8") as f:
        lines = [l.strip() for l in f.read().splitlines() if l.strip()]
    if len(lines) < 2:
        print("[!] email.txt υπάρχει αλλά δεν έχει τις 2 απαραίτητες γραμμές (διεύθυνση, app password).")
        return False
    sender, app_password = lines[0], lines[1]
    recipient = lines[2] if len(lines) > 2 else DEFAULT_REPORT_TO

    subject, body = build_email_report(touched, deploy_ok, backend, error_detail)

    try:
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(sender, app_password)
            server.sendmail(sender, [recipient], msg.as_string())
        print(f"[✓] Email αναφοράς στάλθηκε: {sender} -> {recipient}")
        return True
    except Exception as e:
        print("[!] Αποστολή email ΑΠΕΤΥΧΕ:", e)
        return False


def deploy():
    """Καλεί το υπάρχον monitor.py publish και ΕΠΙΒΕΒΑΙΩΝΕΙ πραγματικό deploy.

    Προσοχή: το `python monitor.py publish` πάντα επιστρέφει exit code 0, ακόμη κι αν
    το ίδιο το deploy αποτύχει (το monitor.py απλώς τυπώνει "[!] ..." και συνεχίζει).
    Άρα ΔΕΝ αρκεί να κοιτάξουμε το returncode — ελέγχουμε επιπλέον αν άλλαξε πραγματικά
    το last_deploy.txt (το μόνο σίγουρο ίχνος επιτυχημένου deploy μέσα στο monitor.py).

    Backend: αν υπάρχει cloudflare.txt, το monitor.py χρησιμοποιεί Cloudflare Pages·
    διαφορετικά πέφτει σε Netlify (παλιά, ξεπερασμένη λύση — το αναφέρουμε ρητά αν συμβεί,
    δεν το κρύβουμε πίσω από ένα γενικό "Cloudflare" μήνυμα).

    Επιστρέφει (ok: bool, backend: str, detail: str).
    """
    marker = os.path.join(HERE, "last_deploy.txt")
    before = open(marker, encoding="utf-8").read().strip() if os.path.exists(marker) else None

    cf_present = os.path.exists(os.path.join(HERE, "cloudflare.txt"))
    backend = "Cloudflare Pages" if cf_present else "Netlify (ΠΡΟΣΟΧΗ: δεν βρέθηκε cloudflare.txt — ξεπερασμένο fallback)"

    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, "monitor.py"), "publish"],
            cwd=HERE, capture_output=True, text=True, timeout=300,
        )
    except Exception as e:
        detail = f"Δεν έτρεξε καν το monitor.py publish: {e}"
        print(f"[DEPLOY FAILED] {detail}")
        return False, backend, detail

    output = (proc.stdout or "") + (proc.stderr or "")
    print(output)

    after = open(marker, encoding="utf-8").read().strip() if os.path.exists(marker) else None
    hash_changed = after is not None and after != before
    looks_ok = "[!]" not in output and "σφάλμα" not in output.lower()
    ok = proc.returncode == 0 and hash_changed and looks_ok

    if ok:
        return True, backend, output

    detail = (f"exit={proc.returncode}, hash πριν={before}, hash μετά={after} "
              f"(hash_changed={hash_changed}), backend={backend}. Έξοδος:\n{output}")
    print(f"[DEPLOY FAILED] Δεν επιβεβαιώθηκε πραγματικό deploy. {detail}")
    return False, backend, detail


if __name__ == "__main__":
    touched, changed_files = run()

    if not touched:
        # τίποτα να δημοσιευτεί· δεν τρέχουμε deploy ούτε γράφουμε manifest, αλλά
        # στέλνουμε ΚΑΙ ΠΑΛΙ την καθημερινή αναφορά (ώστε να είναι όντως καθημερινή,
        # όχι μόνο τις μέρες που άλλαξε κάτι) — χωρίς deploy, backend="—".
        notify_email([], deploy_ok=True, backend="— (καμία αλλαγή σήμερα)")
        sys.exit(0)

    # Γράφουμε τη λίστα αρχείων που επιτρέπεται να προστεθούν στο git (βλ. workflow
    # "Save state" — git add ΜΟΝΟ αυτά, ποτέ `git add -A`).
    with open(CHANGED_FILES_MANIFEST, "w", encoding="utf-8") as f:
        f.write("\n".join(changed_files) + "\n")

    ok, backend, detail = deploy()
    if ok:
        with open(CHANGED_FILES_MANIFEST, "a", encoding="utf-8") as f:
            f.write("last_deploy.txt\nlast_upload_time.txt\n")
        notify_email(touched, deploy_ok=True, backend=backend)
    else:
        notify_email(touched, deploy_ok=False, backend=backend, error_detail=detail)
        # Σταματάμε με σαφές σφάλμα· το GitHub Actions step θα αποτύχει ρητά,
        # άρα δεν θα τρέξει καν το επόμενο "Save state" (git commit/push) — καμία
        # μισοτελειωμένη κατάσταση δεν καταλήγει στο repo.
        print("[FATAL] Deploy δεν επιβεβαιώθηκε — διακοπή χωρίς commit/push.")
        sys.exit(1)
