"""Bot Αλλαγών: παρακολουθεί συγκεκριμένες επίσημες σελίδες επιδομάτων (allages_pages.json)
και ειδοποιεί όταν αλλάξει το κείμενό τους. Η λίστα σελίδων εγκρίνεται από τον χρήστη πριν γεμίσει."""
import json, os, re, hashlib
import registry_db as R

PAGES = os.path.join(R.HERE, "allages_pages.json")
HASHES = os.path.join(R.HERE, "allages_hashes.json")
UA = {"User-Agent": "Mozilla/5.0 (GovWatch registry bot)"}


def page_text(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "header", "footer", "nav", "form", "iframe"]):
        t.decompose()
    node = soup.find("main") or soup.body or soup
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True))


def main(fetch=None, send=R.send_telegram, reg=None):
    pages = json.load(open(PAGES, encoding="utf-8")) if os.path.exists(PAGES) else []
    if not pages:
        print("[allages] Η λίστα σελίδων είναι κενή — τίποτα να ελεγχθεί.")
        return 0, 0
    if fetch is None:
        import requests
        fetch = lambda u: requests.get(u, headers=UA, timeout=30).text
    reg = reg or R.connect()
    old = json.load(open(HASHES, encoding="utf-8")) if os.path.exists(HASHES) else {}
    new, changed = dict(old), []
    for p in pages:
        url = p["url"]
        try:
            h = hashlib.sha256(R.norm(page_text(fetch(url))).encode()).hexdigest()
        except Exception as e:
            print(f"[allages] αποτυχία {url}: {e}")
            continue
        if url in old and old[url] != h:
            changed.append((p.get("name", url), url, old[url], h))
        new[url] = h  # πρώτη φορά = σιωπηλή βάση (baseline)
    for name, url, oh, nh in changed:
        reg.execute("INSERT INTO changes(page_url,name,old_hash,new_hash,detected) VALUES(?,?,?,?,?)",
                    (url, name, oh, nh, R.today().isoformat()))
    reg.commit()
    sent = 0
    if changed:
        msg = "🔄 Αλλαγές σε επίσημες σελίδες\n" + "\n".join(f"• {n}\n  {u}" for n, u, _, _ in changed[:10])
        if send(msg):
            reg.execute("UPDATE changes SET notified=1 WHERE notified=0"); reg.commit()
            sent = len(changed)
        else:
            # δεν στάλθηκε: κράτα τον παλιό hash ώστε να ξαναειδοποιήσει
            for _, url, _, _ in changed:
                new[url] = old[url]
    json.dump(new, open(HASHES, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return len(changed), sent


if __name__ == "__main__":
    print("αλλαγές (εντοπισμένες, ειδοποιήσεις):", main())
