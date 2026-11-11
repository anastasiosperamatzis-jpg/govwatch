# -*- coding: utf-8 -*-
"""
Δοκιμές για τις διορθώσεις του γύρου ελέγχου 11/11/2026 (PR #1):
  1) apply_top_expiry(): "top" σβήνει με βάση deadline/expires + ακριβή ώρα Ελλάδας,
     όχι μόνο σύγκριση ημέρας.
  2) check_stalled_sources(): η κατάσταση "ειδοποιήθηκε σήμερα" καταγράφεται ΜΟΝΟ
     όταν το notify() πέτυχε πραγματικά (ώστε μια αποτυχημένη αποστολή να ξαναδοκιμαστεί).
  3) write_sitemap(): το lastmod ΔΕΝ αλλάζει σε κάθε εκτέλεση — μόνο όταν αλλάζει
     πραγματικά το περιεχόμενο μιας σελίδας (content-hash gating).
  4) items_signature() (site_growth_agent.py): σταθερό hash για ίδιο περιεχόμενο,
     διαφορετικό όταν αλλάζει ανακοίνωση/σειρά — βάση του "όχι καθημερινό rewrite χωρίς αλλαγή".

Τρέχει είτε με pytest (`pytest test_monitor_fixes.py`) είτε απευθείας
(`python test_monitor_fixes.py`). Δεν αγγίζει ΚΑΝΕΝΑ πραγματικό αρχείο κατάστασης
του repo (seen.db, sitemap_lastmod.json, stall_state.json) — όλα τα tests που
κάνουν I/O δουλεύουν σε προσωρινό φάκελο (tempfile) και επαναφέρουν ό,τι global
μεταβλητή του monitor.py άλλαξαν, σε finally.
"""
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime

import monitor as M
import site_growth_agent as A


# ---------------------------------------------------------------------------
# 1) apply_top_expiry — deadline/expires με ακριβή ώρα Ελλάδας
# ---------------------------------------------------------------------------

def test_deadline_exact_time_boundary_1800():
    """Ρητό τεστ στο ζητηθέν σενάριο: προθεσμία 'σήμερα στις 18:00' — πρέπει να
    παραμείνει TOP μέχρι ΚΑΙ τη 17:59:59, και να σβήσει αμέσως μετά τις 18:00:00."""
    m = {"top": True, "date": "2026-11-01", "deadline": "2026-11-11T18:00"}
    before = dict(m)
    M.apply_top_expiry([before], datetime(2026, 11, 11, 17, 59, 59, tzinfo=M.GR_TZ))
    assert before["top"] is True, "πριν τις 18:00 πρέπει να είναι ακόμα TOP"

    after = dict(m)
    M.apply_top_expiry([after], datetime(2026, 11, 11, 18, 0, 1, tzinfo=M.GR_TZ))
    assert after["top"] is False, "μετά τις 18:00:00 πρέπει να έχει σβήσει"
    return "OK — 17:59:59 TOP, 18:00:01 όχι"


def test_deadline_date_only_expires_end_of_day():
    """'deadline': 'YYYY-MM-DD' χωρίς ώρα -> λήγει στο ΤΕΛΟΣ εκείνης της μέρας
    (23:59:59), όχι στην αρχή της."""
    m = {"top": True, "date": "2026-11-01", "deadline": "2026-11-11"}
    still_same_day = dict(m)
    M.apply_top_expiry([still_same_day], datetime(2026, 11, 11, 23, 0, tzinfo=M.GR_TZ))
    assert still_same_day["top"] is True, "ακόμα μέσα στην ίδια μέρα -> πρέπει να είναι TOP"

    next_day = dict(m)
    M.apply_top_expiry([next_day], datetime(2026, 11, 12, 0, 0, 1, tzinfo=M.GR_TZ))
    assert next_day["top"] is False, "επόμενη μέρα -> πρέπει να έχει σβήσει"
    return "OK"


def test_deadline_takes_priority_over_expires():
    m = {"top": True, "date": "2026-11-01", "deadline": "2026-11-20", "expires": "2026-11-05"}
    now = datetime(2026, 11, 10, 12, 0, tzinfo=M.GR_TZ)  # μετά το expires, πριν το deadline
    M.apply_top_expiry([m], now)
    assert m["top"] is True, "το 'deadline' πρέπει να υπερισχύει του 'expires'"
    return "OK"


def test_expires_used_when_no_deadline():
    m = {"top": True, "date": "2026-11-01", "expires": "2026-11-05"}
    M.apply_top_expiry([m], datetime(2026, 11, 6, 0, 0, 1, tzinfo=M.GR_TZ))
    assert m["top"] is False
    return "OK"


def test_fallback_age_limit_when_no_deadline_or_expires():
    """Χωρίς deadline/expires: εφεδρικό όριο TOP_MAX_AGE_DAYS (15) ημερών από τη δημοσίευση."""
    m_recent = {"top": True, "date": "2026-11-01"}
    now = datetime(2026, 11, 10, 12, 0, tzinfo=M.GR_TZ)  # 9 μέρες — μέσα στο όριο
    M.apply_top_expiry([m_recent], now)
    assert m_recent["top"] is True

    m_old = {"top": True, "date": "2026-10-01"}
    M.apply_top_expiry([m_old], now)  # >15 μέρες — πρέπει να σβήσει
    assert m_old["top"] is False
    return "OK"


def test_non_top_items_untouched():
    m = {"top": False, "date": "2000-01-01", "deadline": "2000-01-01"}
    before = json.dumps(m, sort_keys=True)
    M.apply_top_expiry([m], datetime(2026, 11, 11, tzinfo=M.GR_TZ))
    assert json.dumps(m, sort_keys=True) == before, "ένα item χωρίς top δεν πρέπει να αγγιχθεί"
    return "OK"


# ---------------------------------------------------------------------------
# 2) check_stalled_sources — notify() success-gating
# ---------------------------------------------------------------------------

def _make_items_db(rows):
    """rows: [(source, first_seen_iso)] -> in-memory sqlite σαν seen.db."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, source TEXT, title TEXT, "
                "url TEXT, priority TEXT, first_seen TEXT)")
    for source, first_seen in rows:
        con.execute("INSERT INTO items (source, title, url, priority, first_seen) VALUES (?,?,?,?,?)",
                    (source, "t", "u", "green", first_seen))
    con.commit()
    return con


def test_notify_failure_does_not_mark_as_alerted():
    """Το πυρήνα του bug που επισήμανε ο χρήστης (Codex): αν το notify() αποτύχει
    (π.χ. πρόβλημα Telegram), η πηγή ΔΕΝ πρέπει να καταγραφεί ως "ειδοποιήθηκε σήμερα" —
    αλλιώς θα περνούσε 24 ώρες χωρίς καμία νέα προσπάθεια ειδοποίησης."""
    old_date = "2000-01-01T00:00:00"
    con = _make_items_db([("ΔοκιμαστικήΠηγή", old_date)])
    sources = [{"name": "ΔοκιμαστικήΠηγή", "url": "https://example.gr", "stall_days": 5}]

    tmp = tempfile.mkdtemp()
    state_file = os.path.join(tmp, "stall_state.json")
    orig_state_file = M.STALL_STATE_FILE
    orig_notify = M.notify
    try:
        M.STALL_STATE_FILE = state_file
        M.notify = lambda *a, **k: False  # προσομοίωση αποτυχημένης αποστολής
        M.check_stalled_sources(con, sources)
        assert not os.path.exists(state_file) or "ΔοκιμαστικήΠηγή" not in json.load(open(state_file)), \
            "ΔΕΝ πρέπει να καταγραφεί ως ειδοποιημένη όταν το notify() αποτύχει"
    finally:
        M.STALL_STATE_FILE = orig_state_file
        M.notify = orig_notify
        shutil.rmtree(tmp, ignore_errors=True)
    return "OK — αποτυχημένο notify() δεν καταγράφεται, θα ξαναδοκιμαστεί"


def test_notify_success_marks_as_alerted_once_per_day():
    old_date = "2000-01-01T00:00:00"
    con = _make_items_db([("ΔοκιμαστικήΠηγή", old_date)])
    sources = [{"name": "ΔοκιμαστικήΠηγή", "url": "https://example.gr", "stall_days": 5}]

    tmp = tempfile.mkdtemp()
    state_file = os.path.join(tmp, "stall_state.json")
    orig_state_file = M.STALL_STATE_FILE
    orig_notify = M.notify
    calls = []
    try:
        M.STALL_STATE_FILE = state_file
        M.notify = lambda *a, **k: (calls.append(1), True)[1]
        M.check_stalled_sources(con, sources)
        state = json.load(open(state_file, encoding="utf-8"))
        assert state.get("ΔοκιμαστικήΠηγή") == datetime.now().strftime("%Y-%m-%d")
        # δεύτερη κλήση την ΙΔΙΑ μέρα -> ΔΕΝ πρέπει να ξαναστείλει
        M.check_stalled_sources(con, sources)
        assert len(calls) == 1, "δεν πρέπει να ειδοποιεί δύο φορές την ίδια μέρα"
    finally:
        M.STALL_STATE_FILE = orig_state_file
        M.notify = orig_notify
        shutil.rmtree(tmp, ignore_errors=True)
    return "OK"


def test_private_and_rss_sources_never_checked_for_stall():
    con = _make_items_db([])
    sources = [
        {"name": "Ιδιωτική", "url": "https://x.gr", "private": True, "stall_days": 1},
        {"name": "ΡΑΝΤΑΡ", "url": "https://news.google.com/rss", "type": "rss", "stall_days": 1},
    ]
    tmp = tempfile.mkdtemp()
    orig_state_file = M.STALL_STATE_FILE
    orig_notify = M.notify
    calls = []
    try:
        M.STALL_STATE_FILE = os.path.join(tmp, "stall_state.json")
        M.notify = lambda *a, **k: (calls.append(1), True)[1]
        M.check_stalled_sources(con, sources)
        assert not calls, "πηγές 'private' ή 'rss' δεν πρέπει ΠΟΤΕ να ειδοποιούν για στασιμότητα"
    finally:
        M.STALL_STATE_FILE = orig_state_file
        M.notify = orig_notify
        shutil.rmtree(tmp, ignore_errors=True)
    return "OK"


# ---------------------------------------------------------------------------
# 3) write_sitemap — content-hash lastmod gating (χωρίς να αγγίξει το πραγματικό site/)
# ---------------------------------------------------------------------------

def test_sitemap_lastmod_stable_unless_content_changes():
    tmp = tempfile.mkdtemp()
    fake_site = os.path.join(tmp, "site")
    os.makedirs(fake_site)
    with open(os.path.join(fake_site, "index.html"), "w", encoding="utf-8") as f:
        f.write("<html>home</html>")
    with open(os.path.join(fake_site, "demo.html"), "w", encoding="utf-8") as f:
        f.write("<html>v1</html>")

    orig_site, orig_lastmod_file = M.SITE, M.SITEMAP_LASTMOD_FILE
    try:
        M.SITE = fake_site
        M.SITEMAP_LASTMOD_FILE = os.path.join(tmp, "sitemap_lastmod.json")

        M.write_sitemap()
        state1 = json.load(open(M.SITEMAP_LASTMOD_FILE, encoding="utf-8"))
        lastmod1 = state1["/demo"]["lastmod"]

        # ξανατρέχουμε ΧΩΡΙΣ καμία αλλαγή περιεχομένου -> το lastmod ΔΕΝ πρέπει να αλλάξει,
        # ακόμα και αν "σήμερα" στο σύστημα να είναι διαφορετικό (αυτό ήταν το bug 11/11).
        M.write_sitemap()
        state2 = json.load(open(M.SITEMAP_LASTMOD_FILE, encoding="utf-8"))
        assert state2["/demo"]["lastmod"] == lastmod1, \
            "το lastmod δεν πρέπει να αλλάζει όταν δεν άλλαξε το περιεχόμενο"

        # αλλάζουμε ΠΡΑΓΜΑΤΙΚΑ το περιεχόμενο -> το hash ΠΡΕΠΕΙ να προχωρήσει
        with open(os.path.join(fake_site, "demo.html"), "w", encoding="utf-8") as f:
            f.write("<html>v2 — πραγματική αλλαγή</html>")
        M.write_sitemap()
        state3 = json.load(open(M.SITEMAP_LASTMOD_FILE, encoding="utf-8"))
        assert state3["/demo"]["hash"] != state1["/demo"]["hash"]
        return f"OK — lastmod σταθερό χωρίς αλλαγή ({lastmod1}), hash προχωράει με αλλαγή"
    finally:
        M.SITE, M.SITEMAP_LASTMOD_FILE = orig_site, orig_lastmod_file
        shutil.rmtree(tmp, ignore_errors=True)


def test_sitemap_includes_spa_only_canonical_routes():
    """Σελίδες χωρίς δικό τους .html (μόνο SPA-route, π.χ. /sxetika) πρέπει να μπαίνουν
    στο sitemap.xml με το καθαρό URL τους (χωρίς .html)."""
    tmp = tempfile.mkdtemp()
    fake_site = os.path.join(tmp, "site")
    os.makedirs(fake_site)
    with open(os.path.join(fake_site, "index.html"), "w", encoding="utf-8") as f:
        f.write("<html>home</html>")

    orig_site, orig_lastmod_file = M.SITE, M.SITEMAP_LASTMOD_FILE
    try:
        M.SITE = fake_site
        M.SITEMAP_LASTMOD_FILE = os.path.join(tmp, "sitemap_lastmod.json")
        M.write_sitemap()
        xml = open(os.path.join(fake_site, "sitemap.xml"), encoding="utf-8").read()
        for route in ("/sxetika", "/aporrito", "/oroi", "/diafimisi"):
            assert f"<loc>https://epidomatatora.gr{route}</loc>" in xml, f"λείπει το {route} από το sitemap"
            assert f"{route}.html" not in xml
        return "OK — όλες οι SPA-only σελίδες είναι στο sitemap, χωρίς .html"
    finally:
        M.SITE, M.SITEMAP_LASTMOD_FILE = orig_site, orig_lastmod_file
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 4) site_growth_agent.items_signature — βάση του "no-op όταν δεν άλλαξε τίποτα"
# ---------------------------------------------------------------------------

def test_items_signature_stable_for_identical_content():
    items = [{"url": "/a", "title": "Τίτλος Α", "date": "2026-11-01"},
             {"url": "/b", "title": "Τίτλος Β", "date": "2026-11-02"}]
    assert A.items_signature(items) == A.items_signature(list(items))
    return "OK"


def test_items_signature_changes_when_content_changes():
    base = [{"url": "/a", "title": "Τίτλος Α", "date": "2026-11-01"}]
    changed_title = [{"url": "/a", "title": "Τίτλος Α (ενημερωμένος)", "date": "2026-11-01"}]
    new_item = [{"url": "/a", "title": "Τίτλος Α", "date": "2026-11-01"},
                {"url": "/c", "title": "Νέα ανακοίνωση", "date": "2026-11-05"}]
    sig0 = A.items_signature(base)
    assert sig0 != A.items_signature(changed_title)
    assert sig0 != A.items_signature(new_item)
    return "OK"


def test_items_signature_ignores_nothing_but_url_title_date():
    """Το hash πρέπει να αγνοεί πεδία όπως 'text'/'foreas' — μόνο (url,title,date) μετράνε,
    ώστε μικρές διαφορές σε βοηθητικά πεδία να μην προκαλούν ψευδή 'άλλαξε' σήμα."""
    a = [{"url": "/a", "title": "Τ", "date": "2026-11-01", "text": "κείμενο 1", "foreas": "Χ"}]
    b = [{"url": "/a", "title": "Τ", "date": "2026-11-01", "text": "κείμενο 2", "foreas": "Ψ"}]
    assert A.items_signature(a) == A.items_signature(b)
    return "OK"


if __name__ == "__main__":
    tests = [
        ("Deadline με ώρα: TOP έως 17:59:59, σβήνει στις 18:00:01", test_deadline_exact_time_boundary_1800),
        ("Deadline μόνο ημερομηνία: λήγει στο τέλος ΕΚΕΙΝΗΣ της μέρας", test_deadline_date_only_expires_end_of_day),
        ("Το 'deadline' υπερισχύει του 'expires'", test_deadline_takes_priority_over_expires),
        ("'expires' χρησιμοποιείται όταν δεν υπάρχει 'deadline'", test_expires_used_when_no_deadline),
        ("Εφεδρικό όριο 15 ημερών χωρίς deadline/expires", test_fallback_age_limit_when_no_deadline_or_expires),
        ("Items χωρίς 'top' δεν αγγίζονται", test_non_top_items_untouched),
        ("notify() αποτυχία -> ΔΕΝ καταγράφεται ως ειδοποιημένη (ξαναδοκιμή)", test_notify_failure_does_not_mark_as_alerted),
        ("notify() επιτυχία -> καταγράφεται, μία φορά/ημέρα", test_notify_success_marks_as_alerted_once_per_day),
        ("Πηγές private/rss ποτέ δεν ελέγχονται για στασιμότητα", test_private_and_rss_sources_never_checked_for_stall),
        ("sitemap lastmod: σταθερό χωρίς αλλαγή, προχωράει με πραγματική αλλαγή", test_sitemap_lastmod_stable_unless_content_changes),
        ("sitemap: οι SPA-only σελίδες μπαίνουν με καθαρό URL", test_sitemap_includes_spa_only_canonical_routes),
        ("items_signature: σταθερό για ίδιο περιεχόμενο", test_items_signature_stable_for_identical_content),
        ("items_signature: αλλάζει με νέο/αλλαγμένο περιεχόμενο", test_items_signature_changes_when_content_changes),
        ("items_signature: αγνοεί πεδία εκτός (url,title,date)", test_items_signature_ignores_nothing_but_url_title_date),
    ]
    failures = 0
    for name, fn in tests:
        print(f"\n=== {name} ===")
        try:
            result = fn()
            print(f"  ✅ {result}")
        except AssertionError as e:
            failures += 1
            print(f"  ❌ FAIL: {e}")
        except Exception as e:
            failures += 1
            print(f"  ❌ ERROR: {e!r}")

    print(f"\n{'='*60}")
    if failures:
        print(f"❌ {failures} ΔΟΚΙΜΗ(ΕΣ) ΑΠΕΤΥΧΑΝ")
        raise SystemExit(1)
    print("✅ ΟΛΕΣ ΟΙ ΔΟΚΙΜΕΣ ΠΕΡΑΣΑΝ")
