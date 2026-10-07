import datetime as dt, sqlite3, tempfile, os
import registry_db as R, dedupe, bot_allages

def test_dates():
    ref = dt.date(2026, 10, 7)
    assert R.find_dates("Επίδομα 400 ευρώ: Πληρωμή στις 30 Νοεμβρίου", ref)[0][0] == dt.date(2026, 11, 30)
    assert R.find_dates("Παράταση έως 15/10", ref)[0][0] == dt.date(2026, 10, 15)
    assert R.find_dates("αιτήσεις μέχρι 5 Ιανουαρίου", ref)[0][0] == dt.date(2027, 1, 5)

def test_dedupe_and_bots():
    d = tempfile.mkdtemp()
    sp = os.path.join(d, "seen.db")
    s = sqlite3.connect(sp)
    s.execute("CREATE TABLE items(id TEXT, source TEXT, title TEXT, url TEXT, priority TEXT, first_seen TEXT)")
    rows = [("1", "A", "Επίδομα θέρμανσης: Προθεσμία αιτήσεων έως 30 Οκτωβρίου - site1", "u1"),
            ("2", "B", "Επίδομα θέρμανσης: Προθεσμία αιτήσεων έως 30 Οκτωβρίου - site2", "u2"),
            ("3", "A", "Συντάξεις Νοεμβρίου: Πληρωμή στις 27 Οκτωβρίου - site3", "u3")]
    for i, (a, b, t, u) in enumerate(rows):
        s.execute("INSERT INTO items VALUES(?,?,?,?,?,?)", (a, b, t, u, "g", f"2026-10-07T10:0{i}:00"))
    s.commit()
    reg = R.connect(os.path.join(d, "r.db"))
    msgs = []
    now = dt.datetime(2026, 10, 7, 12, 0)
    kw = dict(now=now, seen_path=sp, reg=reg, send=lambda m: msgs.append(m) or True)
    import bot_prothesmies, bot_pliromes
    R.scan_and_notify("deadlines", "deadline_date", "📅", "Προθεσμίες", bot_prothesmies.KW, bot_prothesmies.NEAR, **kw)
    R.scan_and_notify("payments", "pay_date", "💶", "Πληρωμές", bot_pliromes.KW, **kw)
    assert reg.execute("SELECT count(*) FROM deadlines").fetchone()[0] == 1   # διπλότυπο ενώθηκε
    assert reg.execute("SELECT count(*) FROM payments").fetchone()[0] == 1
    assert len(msgs) == 2
    n = len(msgs)
    R.scan_and_notify("deadlines", "deadline_date", "📅", "Προθεσμίες", bot_prothesmies.KW, bot_prothesmies.NEAR, **kw)
    assert len(msgs) == n  # καμία επανάληψη
    assert dedupe.build_topics(sp, reg)[0] == 2

def test_allages_empty():
    assert bot_allages.main() == (0, 0)
