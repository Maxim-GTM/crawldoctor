/**
 * Cross-domain cid propagation test (mechanism level).
 *
 * Runs the REAL app/static/tracker.js inside jsdom to prove:
 *   1. links to the other internal domain get `cd_cid` stamped (proactively),
 *   2. same-origin and external links are left alone,
 *   3. window.open and cross-domain forms are decorated,
 *   4. a page loaded WITH `?cd_cid=` adopts that exact cid.
 *
 * Run: node tests/test_cross_domain_cid.js   (uses jsdom from frontend/node_modules)
 */
const fs = require('fs');
const path = require('path');
const { webcrypto } = require('crypto');
const { JSDOM, VirtualConsole } = require(path.join(__dirname, '..', 'frontend', 'node_modules', 'jsdom'));

// --- load tracker.js and fill serve-time placeholders (mirror app/api/tracking.py) ---
const SRC = fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'tracker.js'), 'utf8')
  .replace(/__TID__/g, JSON.stringify('t'))
  .replace(/__PAGE_URL__/g, JSON.stringify(''))
  .replace(/__VISIT_ID__/g, 'null');

let failures = 0;
function check(name, cond) {
  console.log((cond ? '  PASS  ' : '  FAIL  ') + name);
  if (!cond) failures++;
}

function makePage(url, html, beforeRun) {
  const vc = new VirtualConsole(); // swallow jsdom "Not implemented: navigation" noise
  const dom = new JSDOM(html, { url, runScripts: 'outside-only', virtualConsole: vc });
  const w = dom.window;
  w.crypto = webcrypto;                       // tracker needs crypto.getRandomValues
  if (beforeRun) beforeRun(w);
  w.eval(SRC);
  // ensure the initial proactive sweep ran
  w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
  return dom;
}

function cidOf(href) {
  try { return new URL(href).searchParams.get('cd_cid'); } catch (_) { return null; }
}

// =========================================================================
// PAGE 1 — www.getmaxim.ai : outbound links of every kind + a form
// =========================================================================
const page1Html = `<!doctype html><html><body>
  <a id="cross"  href="https://docs.getbifrost.ai/guide">docs (cross-domain internal)</a>
  <a id="ext"    href="https://www.google.com/search">external</a>
  <a id="same"   href="/pricing">same-origin relative</a>
  <a id="hash"   href="#section">hash</a>
  <form id="f" action="https://app.getbifrost.ai/subscribe" method="get"></form>
</body></html>`;

let openedUrl = null;
const p1 = makePage('https://www.getmaxim.ai/landing', page1Html, (w) => {
  w.open = function (u) { openedUrl = u; return null; }; // record; tracker wraps this
});
const d1 = p1.window.document;

const crossHref = d1.getElementById('cross').href;
const pageCid = cidOf(crossHref);

console.log('\n# Page 1 (www.getmaxim.ai) — proactive link decoration');
check('cross-domain link stamped with cd_cid', !!pageCid);
check('external link NOT decorated', !cidOf(d1.getElementById('ext').href));
check('same-origin link NOT decorated', !cidOf(d1.getElementById('same').href));
check('hash link NOT decorated', !cidOf(d1.getElementById('hash').href));
check('cd_cid matches stored localStorage cid',
      pageCid && pageCid === p1.window.localStorage.getItem('cd_cid_t'));

console.log('\n# Page 1 — cross-domain form gets a hidden cd_cid field');
const hidden = d1.querySelector('#f input[name="cd_cid"]');
check('hidden cd_cid input added to cross-domain form', !!hidden);
check('hidden field value == cid', hidden && hidden.value === pageCid);

console.log('\n# Page 1 — window.open() is decorated');
p1.window.open('https://docs.getbifrost.ai/from-open');
check('window.open url decorated with cd_cid', cidOf(openedUrl) === pageCid);
p1.window.open('https://www.google.com/ext');
check('window.open external url NOT decorated', !cidOf(openedUrl));

console.log('\n# Page 1 — dynamically injected link (SPA) gets decorated');
const a = d1.createElement('a');
a.id = 'dyn'; a.href = 'https://docs.getbifrost.ai/dynamic';
d1.body.appendChild(a);
// MutationObserver is async (microtask); flush then assert
setTimeout(() => {
  check('dynamically added cross-domain link decorated', cidOf(d1.getElementById('dyn').href) === pageCid);

  console.log('\n# Page 1 — fragment fallback (#__cdid) for redirect survival');
  check('cross-domain link ALSO carries #__cdid fragment',
        (new URL(crossHref).hash || '').indexOf('__cdid=' + pageCid) !== -1);
  // a link that already has an in-page anchor must keep it and NOT get __cdid
  const anchored = d1.createElement('a');
  anchored.id = 'anchored'; anchored.href = 'https://docs.getbifrost.ai/overview#install';
  d1.body.appendChild(anchored);

  setTimeout(() => {
    const au = new URL(d1.getElementById('anchored').href);
    check('anchored deep link keeps #install (not clobbered)', au.hash === '#install');
    check('anchored deep link still gets ?cd_cid query', au.searchParams.get('cd_cid') === pageCid);

    // =====================================================================
    // PAGE 2 — docs.getbifrost.ai loaded via the decorated link → adopt cid
    // =====================================================================
    console.log('\n# Page 2 (docs.getbifrost.ai) — adopts cd_cid from the URL');
    const p2 = makePage(crossHref, '<!doctype html><html><body><a id="back" href="https://www.getmaxim.ai/">back</a></body></html>');
    const adopted = p2.window.localStorage.getItem('cd_cid_t');
    check('page 2 adopted the SAME cid that page 1 propagated', adopted === pageCid);
    check('page 2 re-decorates its own outbound link to maxim',
          cidOf(p2.window.document.getElementById('back').href) === adopted);

    // =====================================================================
    // PAGE 3 — simulate the REAL 308: query stripped, only #fragment survives
    //   getbifrost root  ?cd_cid=X#__cdid=X   --308-->   /overview#__cdid=X
    // =====================================================================
    console.log('\n# Page 3 — survives a query-stripping redirect via #fragment');
    const afterRedirect = 'https://docs.getbifrost.ai/overview#__cdid=' + pageCid; // NO query
    const p3 = makePage(afterRedirect, '<!doctype html><html><body></body></html>');
    const adopted3 = p3.window.localStorage.getItem('cd_cid_t');
    check('cid adopted from fragment alone (no query)', adopted3 === pageCid);
    check('our token stripped from the address bar after adoption',
          (p3.window.location.hash || '').indexOf('__cdid') === -1);

    console.log('\n' + (failures === 0 ? 'ALL PASSED' : failures + ' CHECK(S) FAILED'));
    process.exit(failures === 0 ? 0 : 1);
  }, 50);
}, 50);
