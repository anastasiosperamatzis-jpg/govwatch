# -*- coding: utf-8 -*-
"""
Δοκιμές για το φιλτράρισμα του Agent 2 (match_theme).

Τρέχει είτε με pytest (`pytest test_site_growth_agent.py`) είτε απευθείας
(`python test_site_growth_agent.py`) χωρίς καμία εξάρτηση εκτός της βιβλιοθήκης.

Χρησιμοποιεί:
  - πραγματικούς τίτλους από το site/anakoinoseis.json (ρητά σημειωμένο ποιοι είναι)
  - λίγα συνθετικά παραδείγματα για κατηγορίες που δεν υπάρχουν αυτή τη στιγμή στο feed
    (ρητά σημειωμένα ως τέτοια, όχι ως δεδομένα παραγωγής)
"""
import json
import os

import site_growth_agent as A

HERE = os.path.dirname(os.path.abspath(__file__))


def theme(slug):
    return next(t for t in A.THEMES if t["slug"] == slug)


def item(title, text="", foreas=""):
    return {"title": title, "text": text, "foreas": foreas}


# ---------------------------------------------------------------------------
# Παραδείγματα που ΠΡΕΠΕΙ ΝΑ ΑΠΟΡΡΙΠΤΟΝΤΑΙ
# ---------------------------------------------------------------------------

# Πραγματικό item από site/anakoinoseis.json (13/10/2026) — κλήρωση επιτροπής,
# όχι ανακοίνωση για πληρωμές/επιδόματα. Η παλιά (buggy) εκδοχή το έβαζε στη σελίδα
# «Πληρωμές ΔΥΠΑ & e-ΕΦΚΑ» επειδή έψαχνε και στο ελεύθερο κείμενο (text).
REAL_COMMITTEE_LOTTERY = item(
    "Ανακοίνωση διενέργειας δημόσιας κλήρωσης για την ανάδειξη τακτικού και "
    "αναπληρωματικού μέλους της Επιτροπής Προστασίας Ψυχικής Υγείας Ανηλίκων "
    "Καταναλωτών, σύμφωνα με την περ. ε΄ της παρ. 6 του άρθρου 7α του ν. 2251/1994"
)

# Πραγματικό item από site/anakoinoseis.json — πρόγραμμα σχολικών γευμάτων, άσχετο
# με επιδόματα/πληρωμές/συντάξεις.
REAL_SCHOOL_MEALS = item(
    "Ξεκινά την Τρίτη 13/10 το Πρόγραμμα των Σχολικών Γευμάτων για 249.247 μαθητές δημοτικού"
)

# Πραγματικό item — δήλωση υπουργού για επενδύσεις, όπου η παλιά έκδοση το έβαζε
# στη «Ρύθμιση Οφειλών» επειδή το keyword "χρε" ταίριαζε μέσα στη λέξη «Χρειαζόμαστε».
REAL_POLITICAL_QUOTE_INVESTMENTS = item(
    "Κυριάκος Πιερρακάκης: «Πρέπει να συνδέσουμε τις αποταμιεύσεις της Ευρώπης με τις "
    "ευκαιρίες της Ευρώπης» – «Χρειαζόμαστε περίπου 800 δισεκατομμύρια ευρώ πρόσθετων "
    "επενδύσεων κάθε χρόνο. Οι δημόσιοι προϋπολογισμοί από μόνοι τους δεν μπορούν να "
    "χρηματοδοτήσουν τον μετασχηματισμό της Ευρώπης. Θέλουμε ιδιωτικές επενδύσεις»"
)

# Πραγματικό item — ΔΥΠΑ αναφέρεται στον τίτλο, αλλά είναι job-fair, όχι πληρωμή.
REAL_DYPA_JOB_FAIR = item(
    "Περισσότερες από 140 επιχειρήσεις και 3.500 θέσεις εργασίας στην 58η "
    "«Ημέρα Καριέρας» της ΔΥΠΑ στην Αθήνα"
)

# Πραγματικό item — ΔΥΠΑ στον τίτλο, αλλά μητρώο εκπαιδευτικών, όχι πληρωμή.
REAL_DYPA_REGISTRY = item(
    "Ξεκινά η υποβολή αιτήσεων για την 13η Συμπληρωματική Πρόσκληση του "
    "Μητρώου Εκπαιδευτικών της ΔΥΠΑ"
)

# Συνθετικό (δεν υπάρχει αυτή τη στιγμή στο feed) — γενική είδηση, άσχετη.
SYNTHETIC_GENERAL_NEWS = item(
    "Νέο πρόγραμμα Ιντερρεγκ για διασυνοριακή συνεργασία Ελλάδας-Βουλγαρίας"
)

REJECT_CASES = [
    ("pliromes-dypa-efka", REAL_COMMITTEE_LOTTERY, "κλήρωση επιτροπής, όχι πληρωμή"),
    ("pliromes-dypa-efka", REAL_DYPA_JOB_FAIR, "ΔΥΠΑ στον τίτλο, αλλά job fair"),
    ("pliromes-dypa-efka", REAL_DYPA_REGISTRY, "ΔΥΠΑ στον τίτλο, αλλά μητρώο εκπαιδευτικών"),
    ("rythmisi-ofeilon", REAL_POLITICAL_QUOTE_INVESTMENTS, "πολιτική δήλωση, όχι ρύθμιση οφειλών ('χρε' bug)"),
    ("rythmisi-ofeilon", REAL_SCHOOL_MEALS, "σχολικά γεύματα — EXCLUDE_PATTERNS"),
    ("epidoma-paidiou-a21", REAL_SCHOOL_MEALS, "σχολικά γεύματα, όχι Α21"),
    ("epidoma-paidiou-a21", SYNTHETIC_GENERAL_NEWS, "γενική είδηση, άσχετη"),
    ("syntaxeis-pliromes", SYNTHETIC_GENERAL_NEWS, "γενική είδηση, άσχετη"),
    ("syntaxeis-pliromes", REAL_COMMITTEE_LOTTERY, "κλήρωση επιτροπής, όχι συντάξεις"),
]

# ---------------------------------------------------------------------------
# Παραδείγματα που ΠΡΕΠΕΙ ΝΑ ΠΕΡΝΑΝΕ
# ---------------------------------------------------------------------------

REAL_DYPA_EFKA_MAP = item("Ο «χάρτης» των πληρωμών από e-ΕΦΚΑ, ΔΥΠΑ για την περίοδο 5 έως 9 Οκτωβρίου")
REAL_DYPA_SEPT_PAYMENTS = item("Οι πληρωμές Σεπτεμβρίου της ΔΥΠΑ - Αναλυτικά στοιχεία ανά κατηγορία ωφελουμένων")
REAL_A21_PAYMENT = item("ΚΑΤΑΒΟΛΗ ΤΗΣ ΣΥΜΠΛΗΡΩΜΑΤΙΚΗΣ ΠΛΗΡΩΜΗΣ ΕΠΙΔΟΜΑΤΟΣ ΠΑΙΔΙΟΥ (Α21) – ΥΠΟΒΟΛΗ ΝΕΩΝ ΑΙΤΗΣΕΩΝ")
REAL_120_DOSEIS_LAW = item("120 δόσεις για χρέη σε Εφορία και ασφαλιστικά ταμεία: Ο νόμος ψηφίζεται μέσα στον Οκτώβριο – Όλοι οι όροι")
REAL_120_DOSEIS_QUOTE = item(
    "Κυριάκος Πιερρακάκης: «Ο νόμος για τις 120 δόσεις θα ψηφιστεί μέσα στον Οκτώβριο και "
    "θα εφαρμοστεί αμέσως» – «Στο προσχέδιο του προϋπολογισμού υπάρχουν εφεδρείες και για "
    "πιο δύσκολα σενάρια. Θα είμαστε συνεχώς δίπλα στους πολίτες»"
)
# Συνθετικό — τυπικός τίτλος συντάξεων, χωρίς «e-ΕΦΚΑ» στον τίτλο (το θέμα είναι σαφές
# από μόνο του: πρέπει να περάσει χωρίς αναφορά φορέα, όπως ζητήθηκε ρητά).
SYNTHETIC_PENSION_DATES = item("Συντάξεις Νοεμβρίου 2026: Οι ημερομηνίες-κλειδιά για τις πληρωμές")

ACCEPT_CASES = [
    ("pliromes-dypa-efka", REAL_DYPA_EFKA_MAP, "ΔΥΠΑ+ΕΦΚΑ και 'πληρωμών' μαζί στον τίτλο"),
    ("pliromes-dypa-efka", REAL_DYPA_SEPT_PAYMENTS, "ΔΥΠΑ και 'πληρωμές' μαζί στον τίτλο"),
    ("epidoma-paidiou-a21", REAL_A21_PAYMENT, "'Α21' ρητά στον τίτλο"),
    ("rythmisi-ofeilon", REAL_120_DOSEIS_LAW, "'120 δόσεις' + 'Εφορία' στον τίτλο"),
    ("rythmisi-ofeilon", REAL_120_DOSEIS_QUOTE, "'120 δόσεις' ειδική φράση, δεν χρειάζεται 'Εφορία' στον ίδιο τίτλο"),
    ("syntaxeis-pliromes", SYNTHETIC_PENSION_DATES, "'συνταξ' αρκεί μόνη της, χωρίς φορέα στον τίτλο"),
]


def test_reject_cases():
    results = []
    for slug, it, why in REJECT_CASES:
        got = A.match_theme(it, theme(slug))
        results.append((slug, it["title"][:70], why, got))
        assert got is False, f"ΕΠΡΕΠΕ ΝΑ ΑΠΟΡΡΙΦΘΕΙ [{slug}] ({why}): {it['title']!r}"
    return results


def test_accept_cases():
    results = []
    for slug, it, why in ACCEPT_CASES:
        got = A.match_theme(it, theme(slug))
        results.append((slug, it["title"][:70], why, got))
        assert got is True, f"ΕΠΡΕΠΕ ΝΑ ΠΕΡΑΣΕΙ [{slug}] ({why}): {it['title']!r}"
    return results


def test_real_feed_sample_if_present():
    """Αν υπάρχει το πραγματικό site/anakoinoseis.json, ελέγχει ότι καμία ανακοίνωση
    με EXCLUDE_PATTERNS στον τίτλο δεν ταιριάζει ΠΟΤΕ σε καμία θεματική σελίδα."""
    feed_path = os.path.join(HERE, "site", "anakoinoseis.json")
    if not os.path.exists(feed_path):
        return []
    with open(feed_path, encoding="utf-8") as f:
        feed = json.load(f)
    bad_matches = []
    for it in feed:
        title_n = A.norm(it.get("title") or "")
        if any(bad in title_n for bad in A.EXCLUDE_PATTERNS):
            for t in A.THEMES:
                if A.match_theme(it, t):
                    bad_matches.append((t["slug"], it["title"]))
    assert not bad_matches, f"EXCLUDE_PATTERNS παραβιάστηκαν: {bad_matches}"
    return bad_matches


def test_own_pages_excluded_from_candidate_feed():
    """Εντοπίστηκε κατά τον έλεγχο: αφού μια θεματική σελίδα του Agent 2 μπει στο
    manual.json, εμφανίζεται και στο anakoinoseis.json σαν «ανακοίνωση». Χωρίς
    εξαίρεση, ο επόμενος κύκλος θα την έβρισκε ξανά — και μάλιστα λανθασμένα κάτω
    από ΑΛΛΟ θέμα (π.χ. ο τίτλος «Πληρωμές ΔΥΠΑ & e-ΕΦΚΑ» περιέχει «ΕΦΚΑ»+«Πληρωμών»
    και ταίριαζε λανθασμένα και στη σελίδα Συντάξεων). Το run() πρέπει να τις αφαιρεί
    πριν το φιλτράρισμα."""
    own_page_as_feed_item = item(
        "Πληρωμές ΔΥΠΑ & e-ΕΦΚΑ — Ημερολόγιο Πληρωμών",
        foreas="Επιδόματα Τώρα",
    )
    own_page_as_feed_item["url"] = "/pliromes-dypa-efka.html"
    assert own_page_as_feed_item["url"] in A.AGENT2_URLS
    # το ίδιο το match_theme() δεν φιλτράρει με βάση το url (αυτό γίνεται στο run()) —
    # εδώ επιβεβαιώνουμε ότι ΘΑ ταίριαζε λανθασμένα στις Συντάξεις αν δεν αφαιρούνταν,
    # άρα το φιλτράρισμα by-url στο run() είναι απαραίτητο, όχι διακοσμητικό.
    assert A.match_theme(own_page_as_feed_item, theme("syntaxeis-pliromes")) is True
    return "επιβεβαιώθηκε ότι χρειάζεται η εξαίρεση by-url στο run()"


def test_upsert_manual_never_touches_foreign_urls():
    """Στατικός έλεγχος scope: το AGENT2_URLS πρέπει να περιέχει ΑΚΡΙΒΩΣ τα 4 URLs
    των θεμάτων — καμία σελίδα εκτός αυτών δεν μπορεί να γραφτεί από upsert_manual
    (βλ. assert μέσα στο upsert_manual)."""
    expected = {f"/{t['slug']}.html" for t in A.THEMES}
    assert A.AGENT2_URLS == expected
    assert len(A.AGENT2_URLS) == 4
    return sorted(A.AGENT2_URLS)


if __name__ == "__main__":
    # Εκτέλεση χωρίς pytest — τυπώνει αναφορά PASS/FAIL για κάθε περίπτωση.
    tests = [
        ("Απόρριψη άσχετων ανακοινώσεων", test_reject_cases),
        ("Αποδοχή σχετικών ανακοινώσεων", test_accept_cases),
        ("Πραγματικό feed: καμία εξαίρεση να μην περάσει", test_real_feed_sample_if_present),
        ("Self-reference: οι δικές του σελίδες πρέπει να εξαιρούνται", test_own_pages_excluded_from_candidate_feed),
        ("Scope: ποτέ αλλαγή εκτός των 4 URLs", test_upsert_manual_never_touches_foreign_urls),
    ]
    failures = 0
    for name, fn in tests:
        print(f"\n=== {name} ===")
        try:
            result = fn()
        except AssertionError as e:
            failures += 1
            print(f"❌ FAIL: {e}")
            continue
        if fn in (test_reject_cases, test_accept_cases):
            for slug, title, why, got in result:
                expect_false = fn is test_reject_cases
                mark = "✅" if (got is False if expect_false else got is True) else "❌"
                print(f"  {mark} [{slug}] {title}...  ({why}) -> match={got}")
        else:
            print(f"  ✅ OK — {result}")

    print(f"\n{'='*60}")
    if failures:
        print(f"❌ {failures} ΔΟΚΙΜΗ(ΕΣ) ΑΠΕΤΥΧΑΝ")
        raise SystemExit(1)
    print("✅ ΟΛΕΣ ΟΙ ΔΟΚΙΜΕΣ ΠΕΡΑΣΑΝ")
