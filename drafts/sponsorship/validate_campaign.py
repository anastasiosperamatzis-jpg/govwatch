#!/usr/bin/env python3
"""Pre-check (ΟΧΙ ενεργοποίηση) αν ένα campaign-config.json θα επέτρεπε
την εμφάνιση της θέσης χορηγού ΣΗΜΕΡΑ (ώρα Europe/Athens), χωρίς δίκτυο και
χωρίς καμία επίδραση στο πραγματικό site. Το αποτέλεσμα —είτε το κείμενο
κατάστασης, είτε το --render-preview HTML— είναι μόνο πληροφοριακό.

ΔΕΝ υλοποιεί δυναμική λήξη στο live site: δεν υπάρχει κανένας μηχανισμός
που να αφαιρεί αυτόματα τη θέση όταν λήξει το end_date σε πραγματική
παραγωγή. Η πραγματική ενεργοποίηση/απενεργοποίηση γίνεται πάντα χειροκίνητα
(deploy), βλ. activation-and-reporting.md. Αυτό το πακέτο ΔΕΝ είναι έτοιμο
για «ένα κλικ δημοσίευσης».

Χρήση:
  python3 validate_campaign.py                       # κατάσταση campaign-config.json, σήμερα
  python3 validate_campaign.py --as-of 2026-12-01     # με συγκεκριμένη ημερομηνία αναφοράς
  python3 validate_campaign.py --self-test            # 14 σενάρια κατάστασης και HTML, χωρίς δίκτυο
  python3 validate_campaign.py --render-preview       # παράγει το HTML (hidden/ή escaped block) στο stdout
"""
import argparse, html, json, os, re, sys
from datetime import date, datetime
from urllib.parse import urlparse

try:
    from zoneinfo import ZoneInfo
    ATHENS = ZoneInfo("Europe/Athens")
except Exception:
    ATHENS = None

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "campaign-config.json")
DEFAULT_TEMPLATE = os.path.join(HERE, "sponsor-slot.html")
SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
MAX_DURATION_DAYS = 30


def today_athens():
    if ATHENS:
        return datetime.now(ATHENS).date()
    raise RuntimeError("Απαιτείται διαθέσιμη ζώνη ώρας Europe/Athens")


def parse_date(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def is_safe_slug(slug):
    return isinstance(slug, str) and bool(SLUG_RE.fullmatch(slug))


def is_valid_https_url(u):
    """Μόνο https, χωρίς credentials (user:pass@) στο URL."""
    if not isinstance(u, str) or not u or any(c.isspace() or ord(c) < 32 for c in u):
        return False
    try:
        p = urlparse(u)
        hostname = p.hostname
        _ = p.port  # η πρόσβαση ελέγχει και τη σύνταξη/το εύρος της θύρας
        if p.scheme != "https" or not hostname or "." not in hostname:
            return False
        if p.username is not None or p.password is not None:
            return False
        labels = hostname.encode("idna").decode("ascii").rstrip(".").split(".")
        return all(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in labels)
    except Exception:
        return False


def evaluate(campaign, as_of):
    """Επιστρέφει (state, reason) — ΔΕΝ γράφει/αλλάζει τίποτα.
    state ∈ {"ΚΡΥΦΗ", "ΚΡΥΦΗ/ΑΚΥΡΗ", "ΟΡΑΤΗ"}."""
    if campaign.get("active") is not True:  # αυστηρά boolean True, όχι "true"/1/κλπ.
        return "ΚΡΥΦΗ", "active δεν είναι boolean true (ανενεργό εξ ορισμού)"
    try:
        start = parse_date(campaign.get("start_date"))
        end = parse_date(campaign.get("end_date"))
    except (ValueError, TypeError):
        return "ΚΡΥΦΗ/ΑΚΥΡΗ", "άκυρη ημερομηνία"
    if end is None:
        return "ΚΡΥΦΗ/ΑΚΥΡΗ", "λείπει end_date — υποχρεωτικό"
    if start is None:
        return "ΚΡΥΦΗ/ΑΚΥΡΗ", "λείπει start_date — υποχρεωτικό"
    if start > end:
        return "ΚΡΥΦΗ/ΑΚΥΡΗ", f"start_date ({start}) μετά το end_date ({end})"
    duration = (end - start).days + 1  # και η πρώτη και η τελευταία ημέρα είναι ενεργές
    if duration > MAX_DURATION_DAYS:
        return "ΚΡΥΦΗ/ΑΚΥΡΗ", f"διάρκεια {duration} ημερών > {MAX_DURATION_DAYS} μέγιστο"
    if as_of < start:
        return "ΚΡΥΦΗ", f"μελλοντική έναρξη ({start.isoformat()} > σήμερα {as_of.isoformat()})"
    if as_of > end:
        return "ΚΡΥΦΗ", f"ληγμένη ({end.isoformat()} < σήμερα {as_of.isoformat()})"
    if not is_valid_https_url(campaign.get("target_url")):
        return "ΚΡΥΦΗ/ΑΚΥΡΗ", f"άκυρη target_url (πρέπει https, χωρίς credentials): {campaign.get('target_url')!r}"
    if not is_safe_slug(campaign.get("slug")):
        return "ΚΡΥΦΗ/ΑΚΥΡΗ", f"μη ασφαλές slug: {campaign.get('slug')!r}"
    return "ΟΡΑΤΗ", f"active=true, εντός περιόδου ({start}–{end}, ≤{MAX_DURATION_DAYS}ημ), έγκυρο https URL, ασφαλές slug"


HIDDEN_HTML = "<!-- sponsor-slot: καμία ενεργή διαφήμιση σήμερα -->\n"


def render_preview(campaign, as_of, template_path=DEFAULT_TEMPLATE):
    """Παράγει το πραγματικό HTML που θα εμφανιζόταν σήμερα — hidden comment
    για κάθε μη-ΟΡΑΤΗ κατάσταση, ή το πλήρως escaped sponsor-slot block όταν
    η καμπάνια είναι πράγματι έγκυρη και ενεργή. ΔΕΝ γράφει πουθενά."""
    state, reason = evaluate(campaign, as_of)
    if state != "ΟΡΑΤΗ":
        return HIDDEN_HTML, state, reason
    with open(template_path, encoding="utf-8") as f:
        tpl = f.read()
    # Αφαιρεί το εσωτερικό σχόλιο οδηγιών (<!-- ... -->) στην αρχή του template —
    # δεν πρέπει να καταλήγει σε «ζωντανό» προεπισκόπηση HTML.
    tpl = re.sub(r"^\s*<!--.*?-->\s*", "", tpl, count=1, flags=re.DOTALL)
    slug = campaign["slug"]  # ήδη ελεγμένο ασφαλές από το evaluate()
    name = html.escape(campaign.get("sponsor_name") or "")
    desc = html.escape(campaign.get("sponsor_description") or "")
    out = (tpl.replace("SLUG_HERE", html.escape(slug))
              .replace("SPONSOR_NAME_HERE", name)
              .replace("SPONSOR_SHORT_DESCRIPTION_HERE", desc))
    return out, state, reason


def run_self_test():
    """14 σενάρια κατάστασης και αντίστοιχου HTML, χωρίς δίκτυο."""
    today = date(2026, 11, 11)
    base = {"slug": "sponsor-a", "sponsor_name": "<Σπόνσορας> & Co",
            "sponsor_description": "περιγραφή", "start_date": "2026-11-01",
            "end_date": "2026-11-30", "target_url": "https://sponsor-example.gr/"}
    cases = [
        ("ανενεργό", {**base, "active": False}, "ΚΡΥΦΗ"),
        ("μελλοντικό", {**base, "active": True, "start_date": "2027-01-01", "end_date": "2027-01-30"}, "ΚΡΥΦΗ"),
        ("ενεργό", {**base, "active": True}, "ΟΡΑΤΗ"),
        ("ληγμένο", {**base, "active": True, "start_date": "2026-09-01", "end_date": "2026-09-30"}, "ΚΡΥΦΗ"),
        ("άκυρη διεύθυνση (http, όχι https)", {**base, "active": True, "target_url": "http://sponsor-example.gr/"}, "ΚΡΥΦΗ/ΑΚΥΡΗ"),
        ("credentials στο URL", {**base, "active": True, "target_url": "https://u:p@sponsor-example.gr/"}, "ΚΡΥΦΗ/ΑΚΥΡΗ"),
        ("διάρκεια > 30 ημέρες", {**base, "active": True, "start_date": "2026-11-01", "end_date": "2026-12-15"}, "ΚΡΥΦΗ/ΑΚΥΡΗ"),
        ("μη ασφαλές slug", {**base, "active": True, "slug": "../etc"}, "ΚΡΥΦΗ/ΑΚΥΡΗ"),
        ("active string", {**base, "active": "true"}, "ΚΡΥΦΗ"),
        ("active integer", {**base, "active": 1}, "ΚΡΥΦΗ"),
        ("άκυρη ημερομηνία", {**base, "active": True, "end_date": "2026-11-31"}, "ΚΡΥΦΗ/ΑΚΥΡΗ"),
        ("31 συμπεριλαμβανόμενες ημέρες", {**base, "active": True, "end_date": "2026-12-01"}, "ΚΡΥΦΗ/ΑΚΥΡΗ"),
        ("άκυρο port", {**base, "active": True, "target_url": "https://example.org:bad/"}, "ΚΡΥΦΗ/ΑΚΥΡΗ"),
        ("HTML σε άκυρο URL", {**base, "active": True, "target_url": "--><script>alert(1)</script>"}, "ΚΡΥΦΗ/ΑΚΥΡΗ"),
    ]
    ok = True
    for label, cfg, expected in cases:
        state, reason = evaluate(cfg, today)
        passed = state == expected
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {label}: state={state} ({reason}) expected={expected}")
        rendered, r_state, _ = render_preview(cfg, today)
        if r_state == "ΟΡΑΤΗ":
            html_ok = "<section" in rendered and "<script" not in rendered and "&lt;Σπόνσορας&gt;" in rendered
        else:
            html_ok = rendered == HIDDEN_HTML and "<script" not in rendered
        ok = ok and html_ok
        print(f"       render: {'OK' if html_ok else 'ΛΑΘΟΣ'} -> {rendered.strip().splitlines()[0][:70]}")
    print("\nΌλα τα σενάρια (κατάσταση + render):", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--template", default=DEFAULT_TEMPLATE)
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD (default: σήμερα, ώρα Europe/Athens)")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--render-preview", action="store_true", help="τυπώνει το παραγόμενο HTML στο stdout")
    args = ap.parse_args()

    if args.self_test:
        return run_self_test()

    with open(args.config, encoding="utf-8") as f:
        data = json.load(f)
    campaign = data.get("campaign", data)
    as_of = parse_date(args.as_of) if args.as_of else today_athens()

    if args.render_preview:
        rendered, state, reason = render_preview(campaign, as_of, args.template)
        print(rendered, end="" if rendered.endswith("\n") else "\n")
        print(f"\n<!-- κατάσταση={state} λόγος=\"{reason}\" σήμερα={as_of.isoformat()} (Europe/Athens) -->", file=sys.stderr)
        return 0

    state, reason = evaluate(campaign, as_of)
    print(f"Καμπάνια: {campaign.get('slug', '(χωρίς slug)')}")
    print(f"Κατάσταση σήμερα ({as_of.isoformat()}, Europe/Athens): {state}")
    print(f"Λόγος: {reason}")
    print("\nΣημείωση: πληροφοριακό pre-check μόνο. ΔΕΝ υπάρχει δυναμική λήξη στο")
    print("πραγματικό site — η ενεργοποίηση/απενεργοποίηση είναι πάντα χειροκίνητη")
    print("(deploy), βλ. activation-and-reporting.md. Δεν είμαστε έτοιμοι για")
    print("δημοσίευση με ένα κλικ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

