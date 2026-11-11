#!/usr/bin/env python3
"""Pre-check (ΟΧΙ ενεργοποίηση) αν ένα campaign-config.json θα επέτρεπε
την εμφάνιση της θέσης χορηγού ΣΗΜΕΡΑ, χωρίς δίκτυο και χωρίς καμία
επίδραση στο πραγματικό site. Το αποτέλεσμα είναι μόνο πληροφοριακό —
η πραγματική ενεργοποίηση/απενεργοποίηση γίνεται χειροκίνητα, βλ.
activation-and-reporting.md.

Χρήση:
  python3 validate_campaign.py                     # ελέγχει campaign-config.json, σήμερα
  python3 validate_campaign.py --as-of 2026-12-01   # ελέγχει με συγκεκριμένη ημερομηνία αναφοράς
  python3 validate_campaign.py --self-test          # 5 σταθερά σενάρια, χωρίς αρχεία/δίκτυο
"""
import argparse, json, os, sys
from datetime import date, datetime
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "campaign-config.json")


def parse_date(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def is_valid_url(u):
    if not u:
        return False
    try:
        p = urlparse(u)
        return p.scheme in ("http", "https") and bool(p.netloc) and "." in p.netloc
    except Exception:
        return False


def evaluate(campaign, as_of):
    """Επιστρέφει (state, reason) — ΔΕΝ γράφει/αλλάζει τίποτα."""
    if not campaign.get("active"):
        return "ΚΡΥΦΗ", "active=false (ανενεργό εξ ορισμού)"
    start = parse_date(campaign.get("start_date"))
    end = parse_date(campaign.get("end_date"))
    if end is None:
        return "ΚΡΥΦΗ/ΑΚΥΡΗ", "λείπει end_date — υποχρεωτικό, δεν ενεργοποιείται ποτέ χωρίς αυτό"
    if start and as_of < start:
        return "ΚΡΥΦΗ", f"μελλοντική έναρξη ({start.isoformat()} > σήμερα {as_of.isoformat()})"
    if as_of > end:
        return "ΚΡΥΦΗ", f"ληγμένη ({end.isoformat()} < σήμερα {as_of.isoformat()})"
    if not is_valid_url(campaign.get("target_url")):
        return "ΚΡΥΦΗ/ΑΚΥΡΗ", f"άκυρη ή κενή target_url: {campaign.get('target_url')!r}"
    return "ΟΡΑΤΗ", f"active, εντός περιόδου ({start}–{end}), έγκυρο URL"


def run_self_test():
    """5 σταθερά σενάρια, χωρίς αρχεία/δίκτυο: ανενεργό, μελλοντικό, ενεργό, ληγμένο, άκυρη διεύθυνση."""
    today = date(2026, 11, 11)
    base = {"start_date": "2026-11-01", "end_date": "2026-11-30", "target_url": "https://sponsor-example.gr/"}
    cases = [
        ("ανενεργό", {**base, "active": False}, "ΚΡΥΦΗ"),
        ("μελλοντικό", {**base, "active": True, "start_date": "2027-01-01", "end_date": "2027-01-31"}, "ΚΡΥΦΗ"),
        ("ενεργό", {**base, "active": True}, "ΟΡΑΤΗ"),
        ("ληγμένο", {**base, "active": True, "start_date": "2026-09-01", "end_date": "2026-09-30"}, "ΚΡΥΦΗ"),
        ("άκυρη διεύθυνση", {**base, "active": True, "target_url": "not-a-url"}, "ΚΡΥΦΗ/ΑΚΥΡΗ"),
    ]
    ok = True
    for label, cfg, expected in cases:
        state, reason = evaluate(cfg, today)
        passed = state == expected
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {label}: state={state} ({reason}) expected={expected}")
    print("\nΌλα τα σενάρια:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD (default: σήμερα)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return run_self_test()

    with open(args.config, encoding="utf-8") as f:
        data = json.load(f)
    campaign = data.get("campaign", data)
    as_of = parse_date(args.as_of) if args.as_of else date.today()
    state, reason = evaluate(campaign, as_of)
    print(f"Καμπάνια: {campaign.get('slug', '(χωρίς slug)')}")
    print(f"Κατάσταση σήμερα ({as_of.isoformat()}): {state}")
    print(f"Λόγος: {reason}")
    print("\nΣημείωση: αυτό είναι πληροφοριακό pre-check. Δεν αλλάζει το πραγματικό site —")
    print("η πραγματική ενεργοποίηση/απενεργοποίηση γίνεται χειροκίνητα (activation-and-reporting.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
