"""Deduplication: ομαδοποιεί τα items του seen.db (μόνο ανάγνωση) σε «θέματα» στο registry.db.
Ίδιο θέμα από πολλά sites = ένα topic."""
import registry_db as R

SAME_STORY = 0.6


def build_topics(seen_path=R.SEEN, reg=None, since=None):
    reg = reg or R.connect()
    s = R.seen_conn(seen_path)
    q = "SELECT id, source, title, url, first_seen FROM items"
    args = ()
    if since:
        q += " WHERE first_seen > ?"
        args = (since,)
    rows = s.execute(q + " ORDER BY first_seen", args).fetchall()
    s.close()
    clusters = []  # [title, url, first, last, set(sources), n]
    for _id, src, title, url, fs in rows:
        for c in clusters:
            if R.similarity(title, c[0]) >= SAME_STORY:
                c[3] = fs; c[4].add(src); c[5] += 1
                break
        else:
            clusters.append([title, url, fs, fs, {src}, 1])
    for title, url, first, last, srcs, n in clusters:
        key = " ".join(sorted(R.tokens(title)))[:120]
        reg.execute("""INSERT INTO topics(key,title,first_seen,last_seen,n_items,n_sources,url)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET last_seen=excluded.last_seen,
            n_items=n_items+excluded.n_items, n_sources=max(n_sources,excluded.n_sources)""",
                    (key, R.clean_title(title), first, last, n, len(srcs), url))
    reg.commit()
    return len(clusters), len(rows)


def dedupe_items(items):
    """items: λίστα (title, ...) — κρατά το πρώτο από κάθε ομάδα ίδιου θέματος."""
    kept = []
    for it in items:
        if not any(R.similarity(it[0], k[0]) >= SAME_STORY for k in kept):
            kept.append(it)
    return kept


if __name__ == "__main__":
    print("topics, items:", build_topics())
