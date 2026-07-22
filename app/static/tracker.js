/**
 * CrawlDoctor Client-Side Tracker
 *
 * Captures page views, clicks, scrolls, form interactions, and navigation
 * events.  Sends data to the CrawlDoctor backend via sendBeacon / fetch.
 *
 * Template placeholders replaced at serve time:
 *   __TID__              – tracking ID (string literal or "")
 *   __PAGE_URL__         – initial page URL (string literal or "")
 *   __VISIT_ID__         – server-side visit id (number literal or null)
 */
!(function () {
  try {
    var cd = window.CrawlDoctor || (window.CrawlDoctor = {});
    if (cd._loaded) return;
    cd._loaded = true;

    // ---- safe storage accessors ----
    function getStorage(name) {
      try { return window[name]; } catch (_) { return null; }
    }
    var sessionStore = getStorage('sessionStorage');
    var localStore   = getStorage('localStorage');

    function storageGet(store, key) {
      try { return store ? store.getItem(key) : null; } catch (_) { return null; }
    }
    function storageSet(store, key, val) {
      try { if (store) store.setItem(key, val); } catch (_) {}
    }

    storageGet(sessionStore, 'cd_page_view_sent') || storageSet(sessionStore, 'cd_page_view_sent', '1');

    // ---- config from server ----
    var trackingId      = __TID__;
    var _pageUrl        = __PAGE_URL__;  // consumed by comma expr below
    var visitId         = __VISIT_ID__;

    // ---- determine script origin (for beacon URL) ----
    var scriptSrc = (function () {
      var el = document.currentScript;
      if (!el) { var tags = document.getElementsByTagName('script'); el = tags[tags.length - 1]; }
      return (el && el.src) || '';
    })();
    var apiOrigin = (function () {
      try { return new URL(scriptSrc).origin; } catch (_) { return location.protocol + '//' + location.host; }
    })();

    // ---- root domain extraction (for cookies & cross-sub-domain matching) ----
    var MULTI_LEVEL_TLDS = ['co.uk','org.uk','ac.uk','gov.uk','com.au','net.au','co.nz'];
    function getRootDomain(hostname) {
      try {
        var parts = (hostname || location.hostname).split('.');
        if (parts.length <= 2) return parts.join('.');
        var two   = parts.slice(-2).join('.');
        var three = parts.slice(-3).join('.');
        return MULTI_LEVEL_TLDS.indexOf(three) >= 0 ? three : two;
      } catch (_) { return location.hostname; }
    }
    var rootDomain = getRootDomain(location.hostname);

    // ---- internal domain check (Maxim + Bifrost) ----
    var INTERNAL_ROOTS = ['getmaxim.ai', 'getbifrost.ai'];
    function isInternalHost(hostname) {
      var h = (hostname || '').toLowerCase();
      for (var i = 0; i < INTERNAL_ROOTS.length; i++) {
        if (h === INTERNAL_ROOTS[i] || h.endsWith('.' + INTERNAL_ROOTS[i])) return true;
      }
      return false;
    }

    // ---- client ID (cid) ----
    var cidStorageKey = 'cd_cid_' + (trackingId || rootDomain);
    var cid = null;

    // 1. Cross-domain hand-off: read the cid from the URL query, then fall back
    //    to the URL fragment.  Server redirects (307/308/301) that rebuild the
    //    Location header drop the ?query, but the browser re-attaches the
    //    original #fragment onto the redirect target — so #__cdid survives the
    //    apex / bare-root redirects that strip ?cd_cid.
    try {
      var loc = window.location;
      var qs = new URLSearchParams(loc.search);
      var rawHash = (loc.hash || '').replace(/^#/, '');
      var hasHashTok = /(^|&)__cdid=/.test(rawHash);
      if (qs.has('cd_cid') || hasHashTok) {
        cid = qs.get('cd_cid');
        if (!cid && hasHashTok) {
          var hp = new URLSearchParams(rawHash);
          cid = hp.get('__cdid');
          hp.delete('__cdid');
          rawHash = hp.toString(); // only rewrite the hash when OUR token was in it
        }
        qs.delete('cd_cid');
        var cleanQs = qs.toString();
        var cleanUrl = loc.pathname + (cleanQs ? '?' + cleanQs : '') + (rawHash ? '#' + rawHash : '');
        window.history.replaceState({}, document.title, cleanUrl);
      }
    } catch (_) {}

    // 2. localStorage  3. cookie  4. generate new
    try {
      if (!cid) cid = storageGet(localStore, cidStorageKey);
      if (!cid) {
        var cookieMatch = document.cookie.match(new RegExp('(^| )cd_cid=([^;]+)'));
        if (cookieMatch) cid = cookieMatch[2];
      }
      if (!cid) {
        cid = ([1e7]+-1e3+-4e3+-8e3+-1e11).toString().replace(/[018]/g, function (c) {
          return (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16);
        });
      }
      // Persist
      storageSet(localStore, cidStorageKey, cid);
      try {
        var expiry = new Date();
        expiry.setFullYear(expiry.getFullYear() + 1);
        document.cookie = 'cd_cid=' + cid + '; path=/; domain=' + rootDomain +
                          '; expires=' + expiry.toUTCString() + '; samesite=Lax';
      } catch (_) {}
    } catch (_) {}

    // ---- page metadata helper ----
    function getPageMeta() {
      var meta = {};
      try {
        meta.title = document.title;
        var tags = document.getElementsByTagName('meta');
        for (var i = 0; i < tags.length; i++) {
          var name = tags[i].getAttribute('name') || tags[i].getAttribute('property');
          if (name && (name.indexOf('description') >= 0 || name.indexOf('og:title') >= 0 || name.indexOf('keywords') >= 0)) {
            meta[name] = tags[i].getAttribute('content');
          }
        }
      } catch (_) {}
      return meta;
    }

    // ---- cross-domain cid propagation ----
    // getmaxim.ai and getbifrost.ai are different registrable domains, so a
    // cookie cannot carry the cid between them.  We propagate it by stamping a
    // cd_cid query param onto every link / form / programmatic navigation that
    // targets the OTHER internal domain; the receiving tracker adopts it on load.
    //
    // Decoration is PROACTIVE (on load + as the DOM mutates) rather than only at
    // mousedown, so the cid rides along no matter how the link is activated:
    // left/middle/right click, keyboard Enter, cmd-click "open in new tab",
    // touch on mobile, or the host site's own JS reading anchor.href.
    function isCrossDomainInternal(urlObj) {
      try {
        return isInternalHost(urlObj.hostname) && urlObj.origin !== window.location.origin;
      } catch (_) { return false; }
    }

    // Returns a cd_cid-decorated href string, or null if not applicable.
    // Stamps BOTH the query (?cd_cid, primary) and the fragment (#__cdid, a
    // redirect-proof fallback).  The fragment is only added when the link has no
    // existing #fragment, so we never clobber in-page anchors (#section) — those
    // are deep links that rarely redirect, so the query alone suffices for them.
    function decorateHref(href) {
      try {
        var url = new URL(href, window.location.href);
        if (!isCrossDomainInternal(url)) return null;
        var hasQuery = url.searchParams.get('cd_cid') === cid;
        var hasFrag  = /(^|#|&)__cdid=/.test(url.hash);
        var canAddFrag = !url.hash; // no existing fragment to preserve
        if (hasQuery && (hasFrag || !canAddFrag)) return null; // already done
        if (!hasQuery) url.searchParams.set('cd_cid', cid);
        if (canAddFrag) url.hash = '__cdid=' + cid;
        return url.toString();
      } catch (_) { return null; }
    }

    function decorateAnchor(a) {
      try {
        if (!a || a.tagName !== 'A' || !a.href) return;
        var next = decorateHref(a.href);
        if (next) a.href = next;
      } catch (_) {}
    }

    function decorateAnchorsIn(root) {
      try {
        var links = (root && root.getElementsByTagName) ? root.getElementsByTagName('a') : [];
        for (var i = 0; i < links.length; i++) decorateAnchor(links[i]);
      } catch (_) {}
    }

    // Cross-domain form posts: add (or refresh) a hidden cd_cid field.
    function decorateForm(form) {
      try {
        if (!form || form.tagName !== 'FORM') return;
        var action = form.getAttribute('action');
        if (!action) return;
        if (!isCrossDomainInternal(new URL(action, window.location.href))) return;
        var existing = form.querySelector('input[name="cd_cid"]');
        if (existing) { existing.value = cid; return; }
        var inp = document.createElement('input');
        inp.type = 'hidden'; inp.name = 'cd_cid'; inp.value = cid;
        form.appendChild(inp);
      } catch (_) {}
    }

    function decorateFormsIn(root) {
      try {
        var forms = (root && root.getElementsByTagName) ? root.getElementsByTagName('form') : [];
        for (var i = 0; i < forms.length; i++) decorateForm(forms[i]);
      } catch (_) {}
    }

    // Initial sweep once the DOM is ready.
    function decorateInitial() { decorateAnchorsIn(document); decorateFormsIn(document); }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', decorateInitial);
    } else {
      decorateInitial();
    }

    // Just-in-time backstop for links added between mutation batches, and for
    // activation paths (keyboard) that may precede our observer.
    function backstop(evt) {
      try {
        var a = evt.target && evt.target.closest ? evt.target.closest('a') : null;
        if (a) decorateAnchor(a);
      } catch (_) {}
    }
    document.addEventListener('mousedown', backstop, true);
    document.addEventListener('auxclick', backstop, true);   // middle-click
    document.addEventListener('touchstart', backstop, { capture: true, passive: true });
    document.addEventListener('keydown', function (evt) {
      if (evt.key === 'Enter' || evt.key === ' ') backstop(evt);
    }, true);
    document.addEventListener('submit', function (evt) { decorateForm(evt.target); }, true);

    // SPA / dynamically injected links and forms.
    try {
      new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var nodes = muts[i].addedNodes;
          for (var j = 0; j < nodes.length; j++) {
            var n = nodes[j];
            if (!n || n.nodeType !== 1) continue;
            if (n.tagName === 'A') decorateAnchor(n);
            else if (n.tagName === 'FORM') decorateForm(n);
            else { decorateAnchorsIn(n); decorateFormsIn(n); }
          }
        }
      }).observe(document.documentElement, { childList: true, subtree: true });
    } catch (_) {}

    // Programmatic navigation: window.open(url, ...).
    try {
      var _open = window.open;
      window.open = function (u) {
        try {
          if (typeof u === 'string') { var d = decorateHref(u); if (d) arguments[0] = d; }
        } catch (_) {}
        return _open.apply(this, arguments);
      };
    } catch (_) {}

    // ---- client-side data (collected once) ----
    var _clientData = null;
    function getClientData() {
      if (_clientData) return _clientData;
      var d = {};
      try { d.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (_) {}
      try { d.language = navigator.language || navigator.userLanguage; } catch (_) {}
      try { d.screen_resolution = window.screen.width + 'x' + window.screen.height; } catch (_) {}
      try { d.viewport_size = window.innerWidth + 'x' + window.innerHeight; } catch (_) {}
      try { if (navigator.deviceMemory) d.device_memory = navigator.deviceMemory + 'GB'; } catch (_) {}
      try { if (navigator.connection) d.connection_type = navigator.connection.effectiveType || navigator.connection.type; } catch (_) {}
      _clientData = d;
      return d;
    }

    // ---- failed form_submit persistence (recovery on next page load) ----
    var FAILED_EVENTS_KEY = 'cd_failed_form_submits';
    var FAILED_EVENTS_MAX = 20;

    function _persistFailedEvent(body) {
      try {
        var raw = storageGet(localStore, FAILED_EVENTS_KEY);
        var queue = [];
        try { queue = raw ? JSON.parse(raw) : []; } catch (_) { queue = []; }
        if (!Array.isArray(queue)) queue = [];
        while (queue.length >= FAILED_EVENTS_MAX) queue.shift();
        queue.push({ body: body, failed_at: Date.now() });
        storageSet(localStore, FAILED_EVENTS_KEY, JSON.stringify(queue));
      } catch (_) {}
    }

    function _flushFailedEvents() {
      try {
        var raw = storageGet(localStore, FAILED_EVENTS_KEY);
        if (!raw) return;
        var queue = [];
        try { queue = JSON.parse(raw); } catch (_) { return; }
        if (!Array.isArray(queue) || !queue.length) return;
        try { localStore.removeItem(FAILED_EVENTS_KEY); } catch (_) {}
        var url = apiOrigin + '/track/event?tid=' + encodeURIComponent(trackingId || '');
        for (var i = 0; i < queue.length; i++) {
          if (queue[i] && queue[i].body) _sendWithRetry(url, queue[i].body, 0);
        }
      } catch (_) {}
    }

    // ---- priority delivery (fetch with retries, beacon as last resort) ----
    var PRIORITY_MAX_RETRIES = 2;
    function _sendWithRetry(url, body, attempt) {
      try {
        fetch(url, { method: 'POST', body: body, headers: {'Content-Type': 'text/plain'}, keepalive: true })
          .then(function (res) {
            if (!res || res.ok) return;
            if (res.status >= 500 && attempt < PRIORITY_MAX_RETRIES) {
              setTimeout(function () { _sendWithRetry(url, body, attempt + 1); }, 500 * (attempt + 1));
            } else {
              // 4xx (e.g. rate limited) or 5xx retries exhausted — persist for
              // recovery on next page load.
              _persistFailedEvent(body);
            }
          })
          .catch(function () {
            if (attempt < PRIORITY_MAX_RETRIES) {
              setTimeout(function () { _sendWithRetry(url, body, attempt + 1); }, 500 * (attempt + 1));
            } else {
              var queued = false;
              if (navigator.sendBeacon) {
                try { queued = navigator.sendBeacon(url, body); } catch (_) {}
              }
              if (!queued) _persistFailedEvent(body);
            }
          });
      } catch (_) {
        var queued = false;
        if (navigator.sendBeacon) {
          try { queued = navigator.sendBeacon(url, body); } catch (_) {}
        }
        if (!queued) _persistFailedEvent(body);
      }
    }

    // ---- event sender ----
    function sendEvent(eventType, data) {
      try {
        var payload = {
          event_type: eventType,
          page_url: window.location.href,
          referrer: document.referrer || null,
          data: data || {},
          visit_id: visitId,
          tid: trackingId,
          cid: cid,
          client_side_data: getClientData(),
          page_metadata: getPageMeta()
        };
        var url = apiOrigin + '/track/event?tid=' + encodeURIComponent(trackingId || '');
        var body = JSON.stringify(payload);

        // form_submit is the highest-value event: deliver via fetch with
        // retries so transient network errors / 5xx don't lose the lead.
        if (eventType === 'form_submit' && window.fetch) {
          _sendWithRetry(url, body, 0);
          return;
        }

        if (navigator.sendBeacon) {
          try { if (navigator.sendBeacon(url, body)) { return; } } catch (_) {}
        }
        if (window.fetch) {
          try {
            fetch(url, { method: 'POST', body: body, headers: {'Content-Type': 'text/plain'}, keepalive: true })
              .catch(function(){});
          } catch (_) {}
        }
      } catch (_) {}
    }

    // ---- page view (single-fire per pathname+search) ----
    var pvKey = 'cd_pv_' + location.pathname + location.search;
    if (!storageGet(sessionStore, pvKey)) {
      storageSet(sessionStore, pvKey, Date.now());
      sendEvent('page_view', {
        viewport: { w: window.innerWidth, h: window.innerHeight },
        tracking_method: 'javascript',
        cid: cid
      });
    }

    // ---- replay form_submits that failed to send on a previous page ----
    setTimeout(_flushFailedEvents, 2000);

    // ---- click tracking ----
    document.addEventListener('click', function (evt) {
      try {
        var el = evt.target;
        var target = el && el.closest ? el.closest('a,button,[role="button"]') : null;
        if (!target) return;
        sendEvent('click', {
          href: ('A' === target.tagName ? target.href : null) || null,
          text: target.innerText || target.getAttribute('aria-label') || target.name || target.id || null,
          id: target.id || null,
          class: target.className || null,
          tracking_method: 'javascript'
        });
      } catch (_) {}
    }, { passive: true });

    // ---- scroll depth milestone (50% once per page view) ----
    var SCROLL_DEPTH_MILESTONE = 50;
    var _scrollDepth50Sent = false;

    function getScrollPercent() {
      var y = window.scrollY || document.documentElement.scrollTop || 0;
      var docH = document.documentElement.scrollHeight || 0;
      var winH = window.innerHeight || 0;
      if (!docH) return 0;
      return Math.round((y + winH) / docH * 100);
    }

    function checkScrollDepthMilestone() {
      if (_scrollDepth50Sent) return;
      try {
        var pct = getScrollPercent();
        if (pct >= SCROLL_DEPTH_MILESTONE) {
          _scrollDepth50Sent = true;
          var y = window.scrollY || document.documentElement.scrollTop || 0;
          sendEvent('scroll', {
            y: y,
            percent: pct,
            milestone: SCROLL_DEPTH_MILESTONE,
            tracking_method: 'javascript'
          });
        }
      } catch (_) {}
    }

    function resetScrollMilestones() {
      _scrollDepth50Sent = false;
    }

    window.addEventListener('scroll', checkScrollDepthMilestone, { passive: true });
    setTimeout(checkScrollDepthMilestone, 0);
    setTimeout(checkScrollDepthMilestone, 1000);

    // ---- visibility tracking ----
    document.addEventListener('visibilitychange', function () {
      sendEvent('visibility', { state: document.visibilityState, tracking_method: 'javascript' });
    });

    // ---- engagement / heartbeat ----
    var _loadTime = Date.now();
    var _lastActivity = Date.now();

    function getEngagement() {
      var now = Date.now();
      return {
        time_on_page_ms: now - _loadTime,
        idle_time_ms: now - _lastActivity,
        engaged: now - _lastActivity < 30000,
        tracking_method: 'javascript'
      };
    }
    function markActive() { _lastActivity = Date.now(); }

    document.addEventListener('click', markActive, { passive: true });
    document.addEventListener('scroll', markActive, { passive: true });
    document.addEventListener('keypress', markActive, { passive: true });

    setInterval(function () {
      if (document.visibilityState === 'visible') sendEvent('heartbeat', getEngagement());
    }, 30000);

    window.addEventListener('beforeunload', function () {
      try {
        var nav = performance && performance.getEntriesByType ? performance.getEntriesByType('navigation')[0] : null;
        var data = getEngagement();
        data.type = (nav && nav.type) || 'unknown';
        sendEvent('navigate', data);
      } catch (_) {}
    });

    // ---- SPA navigation tracking ----
    var _lastHref = location.href;
    function onNavChange(type) {
      try {
        var href = location.href;
        if (href !== _lastHref) {
          sendEvent('navigation', { type: type, from: _lastHref, to: href, tracking_method: 'javascript' });
          _lastHref = href;
          resetScrollMilestones();
          setTimeout(checkScrollDepthMilestone, 0);
          setTimeout(checkScrollDepthMilestone, 1000);
        }
      } catch (_) {}
    }
    try {
      var _origPush = history.pushState;
      history.pushState = function () { _origPush.apply(history, arguments); onNavChange('pushState'); };
      var _origReplace = history.replaceState;
      history.replaceState = function () { _origReplace.apply(history, arguments); onNavChange('replaceState'); };
      window.addEventListener('popstate', function () { onNavChange('popstate'); });
      window.addEventListener('hashchange', function () { onNavChange('hashchange'); });
    } catch (_) {}

    // ---- form field value sanitization ----
    function sanitizeValue(raw, _unused, fieldName, fieldType) {
      var val = raw || '';
      // Mask sensitive fields
      var isSensitive = (function (name, type) {
        var n = (name || '').toLowerCase();
        if ((type || '').toLowerCase() === 'password') return true;
        var blocked = ['password','pass','pwd','ssn','social','credit','card','cc','cvc','cvv',
                       'otp','token','secret','api_key','apikey','recaptcha','cvn','card_number','cvv2'];
        for (var i = 0; i < blocked.length; i++) { if (n.indexOf(blocked[i]) >= 0) return true; }
        return false;
      })(fieldName, fieldType);
      if (isSensitive) return { value: null, masked: true, length: val.length };

      var trimmed = ('' + val).trim();
      // Reject base64 blobs
      if (trimmed.length > 100 && /^[A-Za-z0-9+\/=]{100,}$/.test(trimmed))
        return { value: null, masked: false, length: trimmed.length, rejected: true };
      // Reject JWTs
      if (trimmed.indexOf('eyJ') === 0 && trimmed.split('.').length === 3)
        return { value: null, masked: false, length: trimmed.length, rejected: true };

      var clean = trimmed.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]/g, '');
      if (clean.length > 0) {
        var printable = clean.match(/[a-zA-Z0-9\s@._\-+(),:;!?'"]/g);
        if ((printable ? printable.length : 0) / clean.length < 0.3)
          return { value: null, masked: false, length: clean.length, rejected: true };
      }
      if (clean.length > 0 && !/[a-zA-Z0-9]/.test(clean))
        return { value: null, masked: false, length: clean.length, rejected: true };

      var maxLen = 1000;
      return { value: clean.length > maxLen ? clean.slice(0, maxLen) : clean, masked: false, length: clean.length, truncated: clean.length > maxLen };
    }

    function shouldSkipField(el, type) {
      try {
        if (!el) return true;
        if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return true;
        var t = (type || '').toLowerCase();
        if (t === 'hidden' || t === 'password' || t === 'submit' || t === 'button' || t === 'reset') return true;
      } catch (_) {}
      return false;
    }

    // ---- form submit tracking ----
    function trackFormSubmit(form) {
      try {
        if (!form) return;
        var now = Date.now();
        if (form._cd_last_submit_ts && now - form._cd_last_submit_ts < 1000) return;
        form._cd_last_submit_ts = now;

        var formId     = form.id || null;
        var formName   = form.getAttribute('name') || null;
        var formAction = form.getAttribute('action') || null;
        var formMethod = (form.getAttribute('method') || 'GET').toUpperCase();

        var result = (function (formEl) {
          var fields = formEl.querySelectorAll('input,textarea,select');
          var filled = 0, values = {};
          fields.forEach(function (field) {
            var ft = (field.getAttribute('type') || '').toLowerCase();
            if (shouldSkipField(field, ft)) return;
            var fn = field.name || field.id || 'field_' + Math.random().toString(36).substr(2, 5);
            var fv = (ft === 'checkbox' || ft === 'radio') ? (field.checked ? '1' : '0') : (field.value || '').trim();
            if (!fv) return;
            var s = sanitizeValue(fv, 0, fn, ft);
            if (s.value !== null) { filled++; values[fn] = s.value; }
          });
          return { filled: filled, values: values };
        })(form);

        sendEvent('form_submit', {
          id: formId, name: formName, action: formAction, method: formMethod,
          filled_fields: result.filled, form_values: result.values,
          tracking_method: 'javascript'
        });
      } catch (_) {}
    }

    // ---- DOM event listeners for forms ----
    document.addEventListener('submit', function (e) {
      try { trackFormSubmit(e.target); } catch (_) {}
    }, true);
    document.addEventListener('click', function (e) {
      try {
        var btn = e.target && e.target.closest ? e.target.closest('button, input') : null;
        if (!btn) return;
        if ((btn.getAttribute('type') || '').toLowerCase() !== 'submit') return;
        var form = btn.form || (btn.closest ? btn.closest('form') : null);
        if (!form) return;
        if (form.checkValidity && !form.checkValidity()) return;
        setTimeout(function () { trackFormSubmit(form); }, 0);
      } catch (_) {}
    }, true);

    // ---- network intercept for external form APIs ----
    var INTERCEPT_RULES = [
      { pattern: /^https:\/\/app\.getmaxim\.ai\/api\//, pathContains: '/sign-up', method: 'POST' },
      { pattern: /^https:\/\/(www\.)?getmaxim\.ai\/bifrost\/api\/enterprise-trial/, method: 'POST' },
      { pattern: /^https:\/\/(www\.)?getmaxim\.ai\/api\//, pathContains: ['/bifrost/book-a-demo', '/bifrost/enterprise'], method: 'POST' },
      { pattern: /^https:\/\/api\.cal\.com\//, pathContains: ['/demo', '/schedule', '/bifrost/book-a-demo', '/bifrost/enterprise'], method: 'POST' }
    ];

    function matchesInterceptRule(url, pagePath) {
      try {
        var fullUrl = new URL(url, window.location.href).href;
        var path = (pagePath || window.location.pathname).toLowerCase();
        for (var i = 0; i < INTERCEPT_RULES.length; i++) {
          var rule = INTERCEPT_RULES[i];
          if (!rule.pattern.test(fullUrl)) continue;
          if (rule.pathContains) {
            var paths = Array.isArray(rule.pathContains) ? rule.pathContains : [rule.pathContains];
            var found = false;
            for (var j = 0; j < paths.length; j++) {
              if (path.indexOf(paths[j].toLowerCase()) >= 0) { found = true; break; }
            }
            if (!found) continue;
          }
          return true;
        }
      } catch (_) {}
      return false;
    }

    function isAnalyticsNoise(url) {
      try {
        var parsed = new URL(url, window.location.href);
        var host = parsed.hostname.toLowerCase();
        var path = parsed.pathname.toLowerCase();
        var noiseHosts = ['posthog','segment','analytics','google-analytics','googletagmanager',
          'amplitude','mixpanel','hotjar','fullstory','heap','intercom','pendo','logrocket',
          'ghost','ph.getmaxim','reo.dev','api.reo.dev','twitter.com','ads.linkedin','cloudflareinsights'];
        for (var i = 0; i < noiseHosts.length; i++) { if (host.indexOf(noiseHosts[i]) >= 0) return true; }
        var noisePaths = ['/analytics/','/tracking/','/telemetry/','/flags/','/decide/','/ghost/event','/adsct'];
        for (var i = 0; i < noisePaths.length; i++) { if (path.indexOf(noisePaths[i]) >= 0) return true; }
      } catch (_) {}
      return false;
    }

    function flattenBody(obj, prefix) {
      var out = {}, count = 0;
      prefix = prefix || '';
      try {
        for (var key in obj) {
          if (count >= 50) break;
          if (!obj.hasOwnProperty(key)) continue;
          var val = obj[key];
          var fullKey = prefix ? prefix + '.' + key : key;
          // Skip analytics / internal keys
          var skip = ['phc_','distinct_id','anonymous','token','uuid','session_id','timestamp','version','api_key','device_id'];
          var isSkip = false;
          for (var i = 0; i < skip.length; i++) { if (fullKey.toLowerCase().indexOf(skip[i]) >= 0) { isSkip = true; break; } }
          if (isSkip) continue;
          if (typeof val === 'string') {
            var s = sanitizeValue(val, 0, fullKey, null);
            if (s.value !== null) { out[fullKey] = s.value; count++; }
          } else if (typeof val === 'number' || typeof val === 'boolean') {
            out[fullKey] = val; count++;
          } else if (typeof val === 'object' && val !== null && prefix.split('.').length < 3) {
            var nested = flattenBody(val, fullKey);
            for (var nk in nested) { if (count >= 50) break; out[nk] = nested[nk]; count++; }
          }
        }
      } catch (_) {}
      return out;
    }

    function interceptNetworkSubmit(url, method, body) {
      try {
        if (!matchesInterceptRule(url, window.location.pathname)) return;
        if (isAnalyticsNoise(url)) return;
        var parsed = (function (raw) {
          try {
            if (!raw) return {};
            if (typeof raw === 'string') {
              try { return flattenBody(JSON.parse(raw)); } catch (_) {}
              try { var p = new URLSearchParams(raw), o = {}; p.forEach(function(v,k){o[k]=v;}); return flattenBody(o); } catch (_) {}
            } else if (typeof raw === 'object') return flattenBody(raw);
          } catch (_) {}
          return {};
        })(body);
        var fieldCount = Object.keys(parsed).length;
        if (fieldCount === 0) return;
        sendEvent('form_submit', {
          id: null, name: null, action: url, method: method,
          filled_fields: fieldCount, form_values: parsed,
          tracking_method: 'javascript', source: 'network_intercept'
        });
      } catch (_) {}
    }

    // Patch fetch
    if (window.fetch) {
      var _origFetch = window.fetch;
      window.fetch = function () {
        var args = arguments;
        var reqUrl = args[0];
        var opts = args[1] || {};
        var method = (opts.method || 'GET').toUpperCase();
        try {
          if (method === 'POST' && matchesInterceptRule(reqUrl, window.location.pathname) && !isAnalyticsNoise(reqUrl)) {
            try { interceptNetworkSubmit(reqUrl, method, opts.body); } catch (_) {}
          }
        } catch (_) {}
        return _origFetch.apply(this, args);
      };
    }

    // Patch XMLHttpRequest
    if (window.XMLHttpRequest) {
      var _XHR = window.XMLHttpRequest;
      var _origOpen = _XHR.prototype.open;
      var _origSend = _XHR.prototype.send;
      _XHR.prototype.open = function (method, url) {
        this._cd_method = method;
        this._cd_url = url;
        return _origOpen.apply(this, arguments);
      };
      _XHR.prototype.send = function (body) {
        try {
          var m = (this._cd_method || '').toUpperCase();
          var u = this._cd_url;
          if (m === 'POST' && u && matchesInterceptRule(u, window.location.pathname)) {
            if (!isAnalyticsNoise(u)) interceptNetworkSubmit(u, m, body);
          }
        } catch (_) {}
        return _origSend.apply(this, arguments);
      };
    }

    // ---- watch for dynamically added forms ----
    try {
      new MutationObserver(function (mutations) {
        mutations.forEach(function (mut) {
          mut.addedNodes.forEach(function (node) {
            if (node.nodeType === 1 && node.tagName === 'FORM') {
              node.addEventListener('submit', function (e) { trackFormSubmit(e.target); }, true);
            }
          });
        });
      }).observe(document.body, { childList: true, subtree: true });
    } catch (_) {}

  } catch (_) {}
})();
