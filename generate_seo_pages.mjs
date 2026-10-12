#!/usr/bin/env node
/*
 * generate_seo_pages.mjs
 * ------------------------------------------------------------
 * Προβλημα που διορθώνει:
 * Το site είναι SPA (Single Page App). Το _redirects κάνει
 *   /* /index.html 200
 * άρα ΚΑΘΕ url (π.χ. /epidomata/enischysi-400-syntaxiouxoi) σερβίρεται
 * αρχικά με το ΓΕΝΙΚΟ <title>/<meta description> της αρχικής σελίδας —
 * το σωστό, ειδικό title μπαίνει μόνο με JavaScript (setMeta()) ΑΦΟΥ
 * φορτώσει η σελίδα. Αποτέλεσμα: η Google δείχνει στα αποτελέσματα
 * αναζήτησης το γενικό "Επιδόματα Τώρα · ..." αντί για το ειδικό τίτλο
 * της κάθε σελίδας -> πολύ χαμηλό CTR ακόμα και σε καλές θέσεις.
 *
 * Λύση: δημιουργούμε ΣΤΑΤΙΚΑ .html αρχεία (ένα ανά επίδομα/πρόγραμμα +
 * ένα ανά βασική ενότητα) που έχουν το ΣΩΣΤΟ title/meta ήδη μέσα στο
 * raw HTML, με το ίδιο ακριβώς <body> (ο ίδιος SPA κώδικας αναλαμβάνει
 * μόλις φορτώσει η σελίδα στον browser — καμία αλλαγή στη λειτουργία
 * του site). Το Cloudflare Pages σερβίρει αυτά τα static αρχεία πριν
 * φτάσει στο _redirects catch-all (clean URLs: /foo -> foo.html).
 *
 * Τρέχει αυτόματα σε κάθε deploy μέσα από το monitor.py (βλ. publish()).
 * Μπορεί να τρέξει και χειροκίνητα: node generate_seo_pages.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SITE = path.join(HERE, "site");
const INDEX_PATH = path.join(SITE, "index.html");

const src = fs.readFileSync(INDEX_PATH, "utf-8");

// ---- 1) Πάρε το EPIDOMATA array ΑΠΟ ΤΟ ΙΔΙΟ ΤΟ index.html (πάντα ενημερωμένο) ----
const m = src.match(/const EPIDOMATA = (\[[\s\S]*?\n\]);/);
if (!m) {
  console.error("[!] generate_seo_pages: δεν βρέθηκε το EPIDOMATA array στο index.html — δεν άλλαξε τίποτα.");
  process.exit(1);
}
const EPIDOMATA = new Function(`return ${m[1]};`)();

function confirmed(b, f) {
  const unconf = Array.isArray(b.anepivevaiota) && b.anepivevaiota.includes(f);
  return !unconf && !!b[f];
}

// ---- 2) Helper: αντικατάσταση ενός μοναδικού tag μέσα στο <head> ----
function replaceOnce(html, regex, replacement, label) {
  if (!regex.test(html)) {
    console.warn(`[!] generate_seo_pages: δεν βρέθηκε ${label} στο template — παραλείπεται.`);
    return html;
  }
  return html.replace(regex, replacement);
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function buildPage({ title, desc, url }) {
  let html = src;
  html = replaceOnce(html, /<title>[^<]*<\/title>/, `<title>${esc(title)}</title>`, "<title>");
  html = replaceOnce(html, /<meta name="description" content="[^"]*">/, `<meta name="description" content="${esc(desc)}">`, "meta description");
  html = replaceOnce(html, /<link rel="canonical" href="[^"]*">/, `<link rel="canonical" href="${esc(url)}">`, "canonical");
  html = replaceOnce(html, /<meta property="og:title" content="[^"]*">/, `<meta property="og:title" content="${esc(title.split(" | ")[0])}">`, "og:title");
  html = replaceOnce(html, /<meta property="og:description" content="[^"]*">/, `<meta property="og:description" content="${esc(desc)}">`, "og:description");
  html = replaceOnce(html, /<meta property="og:url" content="[^"]*">/, `<meta property="og:url" content="${esc(url)}">`, "og:url");
  return html;
}

let written = 0;

// ---- 3) Μία static σελίδα ανά επίδομα/πρόγραμμα (/epidomata/<slug>) ----
const epidomataDir = path.join(SITE, "epidomata");
fs.mkdirSync(epidomataDir, { recursive: true });
for (const b of EPIDOMATA) {
  const hasPoso = confirmed(b, "poso");
  const title = `${b.title}: δικαιούχοι, ${hasPoso ? "ποσό, " : ""}πληρωμή, αίτηση | Επιδόματα Τώρα`;
  const desc = `${b.sum} Ποιοι το δικαιούνται, ${hasPoso ? "ποσό, " : ""}πότε πληρώνεται, πώς γίνεται η αίτηση και επίσημη πηγή.`.slice(0, 160);
  const url = `https://epidomatatora.gr/epidomata/${b.slug}`;
  const html = buildPage({ title, desc, url });
  fs.writeFileSync(path.join(epidomataDir, `${b.slug}.html`), html, "utf-8");
  written++;
}

// ---- 4) Βασικές ενότητες (ίδιο title/desc που ήδη βάζει το JS με setMeta) ----
const SECTIONS = {
  "anakoinoseis": { title: "Ανακοινώσεις ΟΠΕΚΑ, ΔΥΠΑ, e-ΕΦΚΑ, ΑΑΔΕ | Επιδόματα Τώρα", desc: "Οι τελευταίες ανακοινώσεις των επίσημων φορέων για επιδόματα, πληρωμές, συντάξεις και προγράμματα, με σύνδεσμο στην πηγή." },
  "epidomata": { title: "Επιδόματα: ποιοι δικαιούνται, ποσά, προθεσμίες | Επιδόματα Τώρα", desc: "Όλα τα επιδόματα με φίλτρα ανά κατηγορία, φορέα και κατάσταση. Δικαιούχοι, ποσά, προθεσμίες και επίσημη πηγή." },
  "programmata": { title: "Προγράμματα ΔΥΠΑ, απασχόλησης και κατάρτισης | Επιδόματα Τώρα", desc: "Προγράμματα της ΔΥΠΑ, επιδοτούμενα προγράμματα απασχόλησης, κατάρτιση και κοινωνικά προγράμματα, με την επίσημη πηγή." },
  "ekptoseis": { title: "Εκπτώσεις και προνόμια για φοιτητές, ανέργους, οικογένειες και ΑμεΑ | Επιδόματα Τώρα", desc: "Μαγαζιά και επιχειρήσεις με εκπτώσεις και προνόμια για φοιτητές, ανέργους, τρίτεκνους, πολύτεκνους και ΑμεΑ." },
  "syntaxeis": { title: "Συντάξεις: όρια ηλικίας, ποσά, πληρωμές, αναδρομικά | Επιδόματα Τώρα", desc: "Όρια ηλικίας, εθνική σύνταξη, σύνταξη χηρείας και αναπηρίας, πληρωμές, αναδρομικά και νέες ρυθμίσεις, με επίσημη πηγή." },
  "pliromes": { title: "Ημερολόγιο πληρωμών επιδομάτων και συντάξεων | Επιδόματα Τώρα", desc: "Πότε πληρώνονται Α21, επίδομα στέγασης, συντάξεις και άλλες παροχές. Ημερολόγιο με ημερομηνίες που έχουν ανακοινωθεί επίσημα." },
  "piges": { title: "Επίσημες πηγές: ΔΥΠΑ, ΟΠΕΚΑ, e-ΕΦΚΑ, ΑΑΔΕ, υπουργεία | Επιδόματα Τώρα", desc: "Οι επίσημοι φορείς που παρακολουθούμε για επιδόματα, πληρωμές, συντάξεις και προγράμματα, με σύνδεσμο στην ιστοσελίδα τους." },
  "syxnes-erotiseis": { title: "Συχνές ερωτήσεις για επιδόματα και πληρωμές | Επιδόματα Τώρα", desc: "Δεν πήρα το Α21; Πότε πληρώνεται το επίδομα στέγασης; Πότε δίνονται τα 400 €; Απαντήσεις από επίσημες πηγές." },
};
for (const [route, { title, desc }] of Object.entries(SECTIONS)) {
  const url = `https://epidomatatora.gr/${route}`;
  const html = buildPage({ title, desc, url });
  fs.writeFileSync(path.join(SITE, `${route}.html`), html, "utf-8");
  written++;
}

console.log(`[OK] generate_seo_pages: γράφτηκαν ${written} static σελίδες (${EPIDOMATA.length} επιδόματα/προγράμματα + ${Object.keys(SECTIONS).length} ενότητες) με σωστό title/meta στο raw HTML.`);
