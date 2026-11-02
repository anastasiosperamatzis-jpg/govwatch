#!/usr/bin/env node
/*
 * generate_seo_pages.mjs
 * ------------------------------------------------------------
 * Προβλημα που διορθώνει (#1 - title/meta):
 * Το site είναι SPA (Single Page App). Το _redirects κάνει
 *   /* /index.html 200
 * άρα ΚΑΘΕ url (π.χ. /epidomata/enischysi-400-syntaxiouxoi) σερβίρεται
 * αρχικά με το ΓΕΝΙΚΟ <title>/<meta description> της αρχικής σελίδας —
 * το σωστό, ειδικό title μπαίνει μόνο με JavaScript (setMeta()) ΑΦΟΥ
 * φορτώσει η σελίδα. Αποτέλεσμα: η Google δείχνει στα αποτελέσματα
 * αναζήτησης το γενικό "Επιδόματα Τώρα · ..." αντί για το ειδικό τίτλο
 * της κάθε σελίδας -> πολύ χαμηλό CTR ακόμα και σε καλές θέσεις.
 *
 * Προβλημα που διορθώνει (#2 - άδειο σώμα σελίδας, η πραγματική αιτία
 * της απόρριψης από Google AdSense για "χαμηλής αξίας περιεχόμενο"):
 * Μέχρι τώρα το <body> κάθε static σελίδας ήταν ΑΚΡΙΒΩΣ ίδιο με το
 * index.html: <main id="app"></main> εντελώς άδειο. Όλο το περιεχόμενο
 * (δικαιούχοι, ποσό, αίτηση, κλπ) μπαινε ΜΟΝΟ με JavaScript αφού φόρτωνε
 * η σελίδα στον browser. Ένας crawler/bot που δεν τρέχει (ή δεν τρέχει
 * πλήρως) JavaScript έβλεπε λοιπόν ΚΕΝΗ σελίδα.
 *
 * Λύση: δημιουργούμε ΣΤΑΤΙΚΑ .html αρχεία (ένα ανά επίδομα/πρόγραμμα +
 * ένα ανά βασική ενότητα) που έχουν το ΣΩΣΤΟ title/meta ήδη μέσα στο
 * raw HTML. Επιπλέον, ΜΟΝΟ για τις σελίδες επιδομάτων/προγραμμάτων
 * (/epidomata/<slug>), γεμίζουμε και το <main id="app"> με το πραγματικό
 * κείμενο (τι είναι, ποιοι δικαιούνται, ποσό, αίτηση, προθεσμία, επίσημη
 * πηγή) φτιαγμένο ΑΠΟ ΤΑ ΙΔΙΑ δεδομένα (EPIDOMATA) που χρησιμοποιεί ήδη
 * το site — καμία νέα πληροφορία, απλά γραμμένη στατικά εκ των προτέρων.
 * Μόλις φορτώσει η σελίδα στον browser, το ίδιο SPA JavaScript αναλαμβάνει
 * κανονικά και ξαναγράφει το περιεχόμενο (ίδια εμφάνιση για τον
 * επισκέπτη) — καμία αλλαγή στη λειτουργία του site για πραγματικούς
 * χρήστες. Οι βασικές ενότητες (epidomata.html, syntaxeis.html κλπ) ΔΕΝ
 * αλλάζουν ακόμα — μένουν όπως ήταν, με μόνο το title/meta διορθωμένο.
 *
 * Το Cloudflare Pages σερβίρει αυτά τα static αρχεία πριν φτάσει στο
 * _redirects catch-all (clean URLs: /foo -> foo.html).
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

// ---- 2β) Helper functions + renderer για το prerendered περιεχόμενο των σελίδων επιδομάτων ----
// (αντιγραφή/αντιστοίχιση της λογικής viewBenefit() που κάνει το ίδιο το SPA στον browser)
const PENDING = "Αναμένεται επίσημη ανακοίνωση";
const STATUS_LABEL = { open: "Σε ισχύ", wait: "Αναμένεται", past: "Έληξε" };

function unconf(b, f) {
  return Array.isArray(b.anepivevaiota) && b.anepivevaiota.includes(f);
}

function val(b, f) {
  return confirmed(b, f) ? esc(b[f]) : `<span class="pending">${PENDING}</span>`;
}

function fmtNum(d) {
  const x = new Date(d);
  if (isNaN(x.getTime())) return esc(String(d ?? ""));
  return `${String(x.getDate()).padStart(2, "0")}/${String(x.getMonth() + 1).padStart(2, "0")}/${x.getFullYear()}`;
}

function renderBenefitMain(b) {
  const stLabel = STATUS_LABEL[b.status] || STATUS_LABEL.wait;
  const noProth = !b.prothesmia && !unconf(b, "prothesmia");
  const dikaiouxoi = Array.isArray(b.dikaiouxoi) ? b.dikaiouxoi : [];
  const proypotheseisOk = Array.isArray(b.proypotheseis) && !unconf(b, "proypotheseis");
  return `<div class="wrap">
    <nav class="breadcrumb" aria-label="Διαδρομή"><a href="/" data-link>Αρχική</a> / <a href="/epidomata" data-link>Επιδόματα</a> / <span aria-current="page">${esc(b.title)}</span></nav>
    <article class="detail-head">
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center"><span class="status">${esc(stLabel)}</span><span class="tag">${esc(b.foreas || "")}</span></div>
      <h1>${esc(b.title)}</h1>
      <p class="lede">${esc(b.sum || "")}</p>
      <p class="checked">Τελευταία ενημέρωση πληροφορίας: ${fmtNum(b.checked)}</p>
    </article>
    <section class="block"><h2>Τι είναι</h2><p>${esc(b.sum || "")} Αρμόδιος φορέας: ${esc(b.foreas || "")}.</p></section>
    <section class="block"><h2>Ποιοι είναι δικαιούχοι</h2>${
      dikaiouxoi.length
        ? `<ul>${dikaiouxoi.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
        : `<p>Δείτε την επίσημη πηγή για τους όρους δικαιούχων.</p>`
    }</section>
    <section class="block"><h2>Προϋποθέσεις</h2>${
      proypotheseisOk
        ? `<ul>${b.proypotheseis.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
        : `<p>${unconf(b, "proypotheseis") ? PENDING + "." : "Δεν έχουν δημοσιευτεί αναλυτικές προϋποθέσεις."} Δείτε την επίσημη πηγή για το σύνολο των προϋποθέσεων.</p>`
    }</section>
    <section class="block"><h2>Ποσό</h2><p>${val(b, "poso")}</p></section>
    <section class="block"><h2>Πότε πληρώνεται</h2><p>${val(b, "pote")}</p></section>
    <section class="block"><h2>Πώς γίνεται η αίτηση</h2><p><b>${esc(b.aitisi || "")}.</b> ${esc(b.pos || "")}</p></section>
    <section class="block"><h2>Προθεσμία</h2><p>${noProth ? "Δεν έχει ανακοινωθεί προθεσμία για αίτηση." : val(b, "prothesmia")}</p></section>
    <section class="block"><h2>Επίσημη πηγή</h2><p>Η πληροφορία ελέγχθηκε στις ${fmtNum(b.checked)}. Πριν από οποιαδήποτε ενέργεια, διαβάστε την επίσημη ανακοίνωση.</p>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px">
        <a class="btn official" href="${esc(b.official || "")}" target="_blank" rel="noopener">ΕΠΙΣΗΜΗ ΠΗΓΗ</a>
        ${b.source && b.source !== b.official ? `<a class="btn" href="${esc(b.source)}" target="_blank" rel="noopener">Σχετικό δημοσίευμα</a>` : ""}
      </div>
    </section>
    <p class="note">Δεν κάνουμε αιτήσεις για λογαριασμό σας και δεν ζητάμε ποτέ κωδικούς Taxisnet, ΑΜΚΑ ή στοιχεία κάρτας.</p>
  </div>`;
}

function buildPage({ title, desc, url, mainHtml }) {
  let html = src;
  html = replaceOnce(html, /<title>[^<]*<\/title>/, `<title>${esc(title)}</title>`, "<title>");
  html = replaceOnce(html, /<meta name="description" content="[^"]*">/, `<meta name="description" content="${esc(desc)}">`, "meta description");
  html = replaceOnce(html, /<link rel="canonical" href="[^"]*">/, `<link rel="canonical" href="${esc(url)}">`, "canonical");
  html = replaceOnce(html, /<meta property="og:title" content="[^"]*">/, `<meta property="og:title" content="${esc(title.split(" | ")[0])}">`, "og:title");
  html = replaceOnce(html, /<meta property="og:description" content="[^"]*">/, `<meta property="og:description" content="${esc(desc)}">`, "og:description");
  html = replaceOnce(html, /<meta property="og:url" content="[^"]*">/, `<meta property="og:url" content="${esc(url)}">`, "og:url");
  if (mainHtml) {
    html = replaceOnce(
      html,
      /<main id="app" tabindex="-1"><\/main>/,
      `<main id="app" tabindex="-1">${mainHtml}</main>`,
      '<main id="app"> (prerendered content)'
    );
  }
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
  const html = buildPage({ title, desc, url, mainHtml: renderBenefitMain(b) });
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

console.log(`[OK] generate_seo_pages: γράφτηκαν ${written} static σελίδες (${EPIDOMATA.length} επιδόματα/προγράμματα + ${Object.keys(SECTIONS).length} ενότητες) με σωστό title/meta στο raw HTML — τα ${EPIDOMATA.length} επιδόματα/προγράμματα έχουν τώρα και πραγματικό prerendered περιεχόμενο στο <main>.`);
