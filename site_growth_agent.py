#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent 2 — Site Growth Agent (πρώτη έκδοση / MVP)

Σκοπός: να «μεγαλώνει» μόνο του το epidomatatora.gr, χωρίς χειροκίνητη δουλειά.

Τι κάνει σε κάθε εκτέλεση:
  1. Διαβάζει το site/anakoinoseis.json (τις ήδη επαληθευμένες ανακοινώσεις του GovWatch).
  2. Ομαδοποιεί τις ανακοινώσεις σε «θεματικούς κόμβους» (π.χ. Πληρωμές ΔΥΠΑ/e-ΕΦΚΑ,
     Συντάξεις, Επίδομα Παιδιού Α21, Ρυθμίσεις οφειλών) — θέματα που ήδη αποδεδειγμένα
     φέρνουν θέαση (βλ. registry.db) αλλά δεν έχουν ακόμη μία μόνιμη σελίδα-κόμβο στο site.
  3. Φτιάχνει/ανανεώνει μία SEO landing page ανά θέμα, που απλώς παραθέτει (όχι εφευρίσκει)
     τις πραγματικές, ήδη ελεγμένες ανακοινώσεις — άρα καμία πληροφορία δεν «εφευρίσκεται».
  4. Ενημερώνει το manual.json ώστε η σελίδα να μπει στο site.
  5. Καλεί monitor.py publish για να ανέβει το site ΑΜΕΣΩΣ (Cloudflare Pages).
  6. Γράφει σύντομη αναφορά στο site_growth_log.md και (αν υπάρχει telegram.txt) στο Telegram.

Σχεδιασμένο να τρέχει μόνο του, 1 φορά τη μέρα, μέσα από GitHub Actions
(.github/workflows/site-growth-agent.yml) — καμία χειροκίνητη ενέργεια.
"""
import json
import os
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
MANUAL = os.path.join(HERE, "manual.json")
FEED = os.path.join(SITE, "anakoinoseis.json")
LOG = os.path.join(HERE, "site_growth_log.md")
SITE_URL = "https://epidomatatora.gr"

MAX_ITEMS_PER_PAGE = 30
MIN_ITEMS_TO_PUBLISH = 2   # κάτω από αυτό δεν αξίζει ακόμη δική του σελίδα

# ---------------------------------------------------------------------------
# Θεματικοί κόμβοι: κάθε ένας γίνεται μία SEO σελίδα.
# Τα keywords ταιριάζουν με τίτλους/κείμενο ανακοινώσεων ήδη ελεγμένων από το GovWatch.
# ---------------------------------------------------------------------------
THEMES = [
    {
        "slug": "pliromes-dypa-efka",
        "cat": "pliromes",
        "nav": "Πληρωμές ΔΥΠΑ & e-ΕΦΚΑ",
        "h1": "Πληρωμές ΔΥΠΑ & e-ΕΦΚΑ — Ημερολόγιο Πληρωμών",
        "desc": "Όλες οι ανακοινωμένες πληρωμές ΔΥΠΑ και e-ΕΦΚΑ (επιδόματα, παροχές, επιστροφές), με ημερομηνία και επίσημη πηγή. Ενημερώνεται αυτόματα.",
        "keywords": ["δυπα", "εφκα", "πληρωμ", "λογαριασμ", "καταβαλ"],
    },
    {
        "slug": "syntaxeis-pliromes",
        "cat": "syntaxeis",
        "nav": "Συντάξεις — Ημερομηνίες Πληρωμών",
        "h1": "Συντάξεις: Ημερομηνίες Πληρωμών",
        "desc": "Ανακοινώσεις e-ΕΦΚΑ για το πότε πληρώνονται οι συντάξεις κάθε μήνα, με επίσημη πηγή. Ενημερώνεται αυτόματα.",
        "keywords": ["συνταξ", "συνταξιουχ"],
    },
    {
        "slug": "epidoma-paidiou-a21",
        "cat": "paroxes",
        "nav": "Επίδομα Παιδιού (Α21)",
        "h1": "Επίδομα Παιδιού Α21 — Νέα & Ανακοινώσεις",
        "desc": "Όλες οι επίσημες ανακοινώσεις ΟΠΕΚΑ για το Επίδομα Παιδιού Α21: αιτήσεις, πληρωμές, προθεσμίες. Ενημερώνεται αυτόματα.",
        "keywords": ["α21", "επιδομα παιδιου", "οπεκα"],
    },
    {
        "slug": "rythmisi-ofeilon",
        "cat": "forologia",
        "nav": "Ρύθμιση Οφειλών (Εφορία / Ταμεία)",
        "h1": "Ρύθμιση Οφειλών σε Εφορία & Ασφαλιστικά Ταμεία",
        "desc": "Ανακοινώσεις για ρυθμίσεις χρεών (δόσεις) σε Εφορία, e-ΕΦΚΑ και ασφαλιστικά ταμεία, με επίσημη πηγή. Ενημερώνεται αυτόματα.",
        "keywords": ["ρυθμισ", "δοσ", "οφειλ", "χρε", "myaade"],
    },
]


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


def match_theme(item, theme):
    hay = norm((item.get("title") or "") + " " + (item.get("text") or ""))
    return any(kw in hay for kw in theme["keywords"])


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


def upsert_manual(theme, n_items):
    items = load_manual()
    url = f"/{theme['slug']}.html"
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
    if not feed:
        print("[!] Δεν βρέθηκε/άδειο το site/anakoinoseis.json — τίποτα να επεξεργαστώ.")
        return []

    report_lines = [f"## Agent 2 — Site Growth · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"]
    touched = []

    for theme in THEMES:
        matches = [it for it in feed if match_theme(it, theme)]
        matches.sort(key=lambda it: it.get("date", ""), reverse=True)
        if len(matches) < MIN_ITEMS_TO_PUBLISH:
            continue
        html = build_page_html(theme, matches)
        path = os.path.join(SITE, f"{theme['slug']}.html")
        existed = os.path.exists(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        action = upsert_manual(theme, len(matches))
        touched.append((theme, len(matches), action))
        verb = "Ανανεώθηκε" if existed else "✨ Δημιουργήθηκε νέα σελίδα"
        report_lines.append(f"- {verb}: **{theme['nav']}** — {len(matches)} ανακοινώσεις — /{theme['slug']}.html")

    if not touched:
        report_lines.append("- Καμία αλλαγή (δεν υπήρχαν αρκετές νέες ανακοινώσεις ανά θέμα).")

    report = "\n".join(report_lines) + "\n"
    print(report)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("\n" + report)

    return touched


def notify_telegram(touched):
    token, chat = None, None
    path = os.path.join(HERE, "telegram.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = [l.strip() for l in f.read().splitlines() if l.strip()]
        if lines:
            token = lines[0]
        if len(lines) > 1:
            chat = lines[1]
    token = os.getenv("TELEGRAM_TOKEN", token)
    chat = os.getenv("TELEGRAM_CHAT_ID", chat)
    if not (token and chat):
        return
    if not touched:
        return
    try:
        import requests
        lines = ["🌱 Agent 2 (Site Growth) ενημέρωσε το site:"]
        for theme, n, action in touched:
            verb = "νέα σελίδα" if action == "created" else "ανανεώθηκε"
            lines.append(f"• {theme['nav']} — {verb} ({n} ανακοινώσεις)")
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": "\n".join(lines)}, timeout=20)
    except Exception as e:
        print("[!] Telegram report failed:", e)


def deploy():
    """Καλεί το ήδη υπάρχον monitor.py publish για άμεσο ανέβασμα στο Cloudflare Pages."""
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "monitor.py"), "publish"],
                        check=False, cwd=HERE)
    except Exception as e:
        print("[!] Deploy call failed:", e)


if __name__ == "__main__":
    touched = run()
    if touched:
        deploy()
        notify_telegram(touched)
