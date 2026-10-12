# -*- coding: utf-8 -*-
"""
Δοκιμές για το generate_seo_pages.mjs.

Το πρόβλημα που διορθώνει το script: το site είναι SPA και το _redirects
σερβίρει ΚΑΘΕ url με το γενικό <title>/<meta description> της αρχικής σελίδας
("Επιδόματα Τώρα · Επιδόματα, πληρωμές, συντάξεις και προγράμματα") — το σωστό
title μπαίνει μόνο με JS, αφού φορτώσει η σελίδα. Αυτό το test επιβεβαιώνει ότι
οι static σελίδες που παράγει το script έχουν ΗΔΗ το σωστό, ειδικό title/meta
μέσα στο raw HTML — όχι το γενικό.

Τρέχει είτε με pytest (`pytest test_generate_seo_pages.py`) είτε απευθείας
(`python test_generate_seo_pages.py`).
"""
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
GENERIC_TITLE = "Επιδόματα Τώρα · Επιδόματα, πληρωμές, συντάξεις και προγράμματα"

GENERATOR = os.path.join(HERE, "generate_seo_pages.mjs")


def _run_generator():
    r = subprocess.run(["node", GENERATOR], cwd=HERE, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"generate_seo_pages.mjs απέτυχε: {r.stderr}"
    return r.stdout


def _title_of(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"<title>([^<]*)</title>", html)
    assert m, f"δεν βρέθηκε <title> στο {path}"
    return m.group(1)


def _desc_of(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r'<meta name="description" content="([^"]*)">', html)
    assert m, f"δεν βρέθηκε meta description στο {path}"
    return m.group(1)


def test_generator_runs_without_error():
    out = _run_generator()
    assert "γράφτηκαν" in out


def test_benefit_pages_have_specific_title_not_generic():
    _run_generator()
    # Τα δύο προβληματικά cases από το Search Console (81 εμφανίσεις, 0 κλικ / θέση ~28, 0 κλικ)
    # συν ένα ακόμα, όλα πρέπει τώρα να έχουν δικό τους title.
    cases = {
        "enischysi-400-syntaxiouxoi": "Ενίσχυση 400",
        "elaxisto-eggyimeno-eisodima": "Ελάχιστο Εγγυημένο Εισόδημα",
        "dorean-ergastiria-dypa-oktovriou": "Δωρεάν εργαστήρια",
        "epidoma-paidiou-a21": "Επίδομα Παιδιού",
    }
    for slug, expect_substr in cases.items():
        path = os.path.join(SITE, "epidomata", f"{slug}.html")
        assert os.path.isfile(path), f"λείπει {path}"
        title = _title_of(path)
        assert title != GENERIC_TITLE, f"{slug}: ακόμα έχει το γενικό title"
        assert expect_substr in title, f"{slug}: title={title!r} δεν περιέχει {expect_substr!r}"
        assert title.endswith("| Επιδόματα Τώρα")


def test_benefit_pages_description_not_generic_and_within_length():
    _run_generator()
    path = os.path.join(SITE, "epidomata", "enischysi-400-syntaxiouxoi.html")
    desc = _desc_of(path)
    assert "Ετήσια ενίσχυση" in desc
    assert len(desc) <= 160


def test_section_pages_have_specific_title():
    _run_generator()
    expected = {
        "programmata.html": "Προγράμματα ΔΥΠΑ",
        "syntaxeis.html": "Συντάξεις:",
        "pliromes.html": "Ημερολόγιο πληρωμών",
        "epidomata.html": "Επιδόματα: ποιοι δικαιούνται",
    }
    for fn, expect_substr in expected.items():
        path = os.path.join(SITE, fn)
        assert os.path.isfile(path), f"λείπει {path}"
        title = _title_of(path)
        assert title != GENERIC_TITLE
        assert expect_substr in title


def test_body_identical_to_index_html():
    """Η static σελίδα πρέπει να έχει ΑΚΡΙΒΩΣ το ίδιο <body> (ο ίδιος SPA κώδικας) —
    αλλάζει μόνο το <head>. Αν αυτό το test σπάσει, κάτι αντιγράφτηκε λάθος."""
    _run_generator()
    with open(os.path.join(SITE, "index.html"), encoding="utf-8") as f:
        index_html = f.read()
    with open(os.path.join(SITE, "epidomata", "enischysi-400-syntaxiouxoi.html"), encoding="utf-8") as f:
        page_html = f.read()
    index_body = index_html[index_html.index("<body>"):]
    page_body = page_html[page_html.index("<body>"):]
    assert index_body == page_body


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"OK   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    if failed:
        raise SystemExit(f"{failed} δοκιμή/-ές απέτυχαν")
    print(f"Όλες οι {len(tests)} δοκιμές πέρασαν.")
