// test_theme_sync_touch_menu.mjs — node harness for the theme_sync and
// touch_model_menu slices ported from upstream PR #34.
//
// Theme sync (web/src/patches/theme_sync/*): resolution order is now
// body classList > Android.getTheme() > initial host theme > media query,
// with a <meta name="color-scheme"> kept in sync, and the native Android
// theme is only persisted from a body-class transition after boot
// (never during the initial pre-React load). install() runs immediately.
//
// Touch model menu (web/src/patches/touch_model_menu/*): scan debounce
// 180ms -> 80ms, the panel observer is armed on demand (pointerdown /
// click on the trigger or panel) and disconnected when the panel closes.
// Two upstream defects are repaired in the fork (see scan.js / install.js
// comments): scan() calls enhanceGroup(), which exists nowhere upstream,
// and install() dropped the detectTouch() call, leaving state.hasTouch
// false forever.
//
// Run: node web/tests/test_theme_sync_touch_menu.mjs
// (also driven by web/tests/test_theme_sync_touch_menu.py)
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const WEB = new URL('..', import.meta.url);
const read = (rel) => readFileSync(new URL(rel, WEB), 'utf8');

const THEME_FRAGS = [
  'src/patches/theme_sync/config.js',
  'src/patches/theme_sync/resolve.js',
  'src/patches/theme_sync/notify.js',
  'src/patches/theme_sync/install.js',
  'src/patches/theme_sync/public-api.js',
];
const TOUCH_FRAGS = [
  'src/patches/touch_model_menu/config.js',
  'src/patches/touch_model_menu/state.js',
  'src/patches/touch_model_menu/detect.js',
  'src/patches/touch_model_menu/synth.js',
  'src/patches/touch_model_menu/open.js',
  'src/patches/touch_model_menu/register.js',
  'src/patches/touch_model_menu/scan.js',
  'src/patches/touch_model_menu/install.js',
  'src/patches/touch_model_menu/public-api.js',
];

// ---------------------------------------------------------------- fake DOM
class FakeClassList {
  constructor(classes = []) { this._set = new Set(classes); }
  contains(c) { return this._set.has(c); }
  add(c) { this._set.add(c); }
  remove(c) { this._set.delete(c); }
  toggle(c, force) {
    if (force === undefined) { this._set.has(c) ? this._set.delete(c) : this._set.add(c); }
    else if (force) this._set.add(c);
    else this._set.delete(c);
    return this._set.has(c);
  }
}

function fakeEl(name, extra = {}) {
  const listeners = {};
  return {
    __name: name,
    classList: new FakeClassList(extra.classes || []),
    style: {},
    parentElement: extra.parentElement || null,
    closest: (sel) => (extra.closestMap && extra.closestMap[sel]) || null,
    addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
    dispatchEvent: () => true,
    focus: () => {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 10, height: 10 }),
    setAttribute: function (k, v) { (this._attrs ||= {})[k] = v; },
    getAttribute: function (k) { return (this._attrs || {})[k]; },
    appendChild: () => {},
    _listeners: listeners,
  };
}

// ---------------------------------------------------------------- theme sync
function makeThemeSandbox(opts = {}) {
  const {
    search = '', hostTheme, androidTheme, android = true,
    bodyClasses = [], mediaDark = false, withBody = true,
    readyState = 'complete',
  } = opts;
  const androidCalls = { setThemeByUser: [], setTheme: [], onVisualThemeChanged: [] };
  const metaEl = fakeEl('meta');
  let metaCreated = false;
  const docEl = fakeEl('html');
  const body = withBody ? fakeEl('body', { classes: bodyClasses }) : null;
  const observers = [];
  const docListeners = {};
  class MutationObserver {
    constructor(cb) { this.cb = cb; }
    observe(target, o) { observers.push({ target, opts: o }); }
    disconnect() {}
  }
  const document = {
    documentElement: docEl,
    body,
    head: { appendChild: () => { metaCreated = true; } },
    readyState,
    querySelector: (sel) => (sel === 'meta[name="color-scheme"]' && metaCreated ? metaEl : null),
    createElement: (tag) => (tag === 'meta' ? metaEl : fakeEl(tag)),
    addEventListener: (type, fn) => { (docListeners[type] ||= []).push(fn); },
  };
  const window = {
    document,
    location: { search },
    MutationObserver,
    matchMedia: (q) => ({
      matches: q.includes('prefers-color-scheme: dark') ? mediaDark : false,
      addEventListener: () => {},
    }),
    addEventListener: () => {},
  };
  if (hostTheme !== undefined) window.__AG_HOST_THEME__ = hostTheme;
  if (android) {
    window.Android = {
      getTheme: () => androidTheme,
      setThemeByUser: (t) => androidCalls.setThemeByUser.push(t),
      setTheme: (t) => androidCalls.setTheme.push(t),
      onVisualThemeChanged: (t) => androidCalls.onVisualThemeChanged.push(t),
    };
  }
  // URLSearchParams is a WebView global, but a node vm context does not
  // provide it — pass the host's through. Same for bare MutationObserver:
  // in a WebView window IS the global scope, but here window is a
  // separate object, so the fragments' bare `new MutationObserver(...)`
  // needs it as a top-level global too.
  const sandbox = { window, document, console, setTimeout, clearTimeout, URLSearchParams, MutationObserver };
  vm.createContext(sandbox);
  const src = THEME_FRAGS.map(read).join('\n');
  vm.runInContext('(function(){\n' + src + '\n})();', sandbox, { filename: 'theme_sync.js' });
  return {
    sandbox, androidCalls, metaEl, observers, docListeners,
    probe: () => sandbox.window.__agThemeSync.probe(),
    sync: () => sandbox.window.__agThemeSync.sync(),
    get metaCreated() { return metaCreated; },
    body,
  };
}

// 1. body class beats Android beats host.
{
  const t = makeThemeSandbox({ bodyClasses: ['theme-dark'], androidTheme: 'light', hostTheme: 'dark' });
  assert.equal(t.probe().theme, 'dark');
  assert.equal(t.metaEl.getAttribute('content'), 'dark');
}
// 2. Android beats host when there is no body class.
{
  const t = makeThemeSandbox({ androidTheme: 'light', hostTheme: 'dark' });
  assert.equal(t.probe().theme, 'light');
  assert.equal(t.metaEl.getAttribute('content'), 'only light');
}
// 3. host beats the media query.
{
  const t = makeThemeSandbox({ android: false, hostTheme: 'dark', mediaDark: false });
  assert.equal(t.probe().theme, 'dark');
}
// 4. invalid host theme falls back to 'system', then the media query.
{
  const t = makeThemeSandbox({ android: false, hostTheme: 'blue', mediaDark: true });
  assert.equal(t.probe().hostTheme, 'system');
  assert.equal(t.probe().theme, 'dark');
}
// 5. nothing set at all -> light, meta says "only light".
{
  const t = makeThemeSandbox({ android: false, mediaDark: false });
  assert.equal(t.probe().theme, 'light');
  assert.equal(t.metaEl.getAttribute('content'), 'only light');
}
// 6. host theme from the URL query param.
{
  const t = makeThemeSandbox({ search: '?hostTheme=dark', android: false, mediaDark: false });
  assert.equal(t.probe().hostTheme, 'dark');
  assert.equal(t.probe().theme, 'dark');
}
// 7. native persistence guard: boot notify never persists, a later body
//    transition does, and a no-change sync notifies nothing.
{
  const t = makeThemeSandbox({ bodyClasses: ['theme-dark'], androidTheme: 'dark' });
  assert.equal(t.probe().notifications, 1, 'install() must notify once at load');
  assert.deepEqual(t.androidCalls.setThemeByUser, [], 'boot must not persist the theme to Android');
  assert.deepEqual(t.androidCalls.onVisualThemeChanged, ['dark']);
  t.body.classList.remove('theme-dark');
  t.body.classList.add('theme-light');
  t.sync();
  assert.equal(t.probe().notifications, 2);
  assert.deepEqual(t.androidCalls.setThemeByUser, ['light'], 'body transition after boot must persist');
  assert.deepEqual(t.androidCalls.onVisualThemeChanged, ['dark', 'light']);
  assert.equal(t.metaEl.getAttribute('content'), 'only light');
  t.sync();
  assert.equal(t.probe().notifications, 2, 'no-change sync must not notify again');
}
// 8. install() runs immediately, even while the document is still loading.
{
  const t = makeThemeSandbox({ readyState: 'loading', bodyClasses: ['theme-dark'] });
  assert.equal(t.probe().installed, true);
  assert.ok(t.observers.length >= 2, 'documentElement and body must be observed at load');
  assert.equal(t.probe().notifications, 1);
}
// 9. body missing at load: observed once it appears via DOMContentLoaded.
{
  const t = makeThemeSandbox({ withBody: false });
  const bodyTargets = t.observers.filter((o) => o.target === null || o.target.__name === 'body');
  assert.equal(bodyTargets.length, 0, 'no body to observe yet');
  const before = t.probe().notifications;
  t.sandbox.document.body = fakeEl('body', { classes: ['theme-light'] });
  for (const fn of t.docListeners.DOMContentLoaded || []) fn();
  assert.ok(t.observers.some((o) => o.target && o.target.__name === 'body'), 'body must be observed after DOMContentLoaded');
  assert.ok(t.probe().notifications > before, 'notify() must run after the body appears');
}

// ---------------------------------------------------------------- touch menu
function makeTouchSandbox({ touch = true, panelOpen = false, groupCount = 0 } = {}) {
  const counts = { effortQueries: 0 };
  const docHandlers = {};
  const observerLog = { created: [], observed: [], disconnected: 0 };
  let panelEl = panelOpen ? fakeEl('panel') : null;
  const triggerEl = fakeEl('trigger', { closestMap: { '[data-testid="model-selector-trigger"]': null } });
  triggerEl.closest = (sel) => (sel === '[data-testid="model-selector-trigger"]' ? triggerEl : null);
  const rootEl = fakeEl('root');
  const document = {
    body: fakeEl('body'),
    documentElement: fakeEl('html'),
    readyState: 'complete',
    querySelector: (sel) => {
      if (sel === '[data-testid="model-selector-panel"]') return panelEl;
      if (sel === '[data-testid="model-selector-trigger"]') return triggerEl;
      if (sel === '#root') return rootEl;
      return null;
    },
    querySelectorAll: (sel) => {
      if (sel === '[data-testid="model-selector-effort-group"]') {
        // Effort groups only exist in the DOM while the panel is open.
        if (!panelEl) return [];
        counts.effortQueries++;
        return Array.from({ length: groupCount }, (_, i) => {
          const row = fakeEl('row' + i);
          const group = fakeEl('group' + i, {
            parentElement: row,
            closestMap: { '[role="menuitem"]': row },
          });
          return group;
        });
      }
      return [];
    },
    addEventListener: (type, fn) => { (docHandlers[type] ||= []).push(fn); },
  };
  class MutationObserver {
    constructor(cb) { this.cb = cb; observerLog.created.push(this); }
    observe(target, o) { observerLog.observed.push({ target, opts: o }); }
    disconnect() { observerLog.disconnected++; }
  }
  const window = {
    document,
    MutationObserver,
    matchMedia: (q) => ({
      matches: q.includes('coarse') ? touch : false,
      addEventListener: () => {},
    }),
    addEventListener: () => {},
  };
  if (touch) window.ontouchstart = null;
  const navigator = { maxTouchPoints: touch ? 1 : 0 };
  // Bare MutationObserver, like in the theme sandbox: the fragments call
  // `new MutationObserver(...)` without the window. prefix.
  const sandbox = { window, document, navigator, console, setTimeout, clearTimeout, MutationObserver };
  vm.createContext(sandbox);
  const src = TOUCH_FRAGS.map(read).join('\n');
  vm.runInContext('(function(){\n' + src + '\n})();', sandbox, { filename: 'touch_model_menu.js' });
  return {
    sandbox, counts, docHandlers, observerLog,
    probe: () => sandbox.window.__agTouchModelMenu.probe(),
    setPanelOpen: (open) => { panelEl = open ? fakeEl('panel') : null; },
    fireDoc: (type, target) => {
      for (const fn of docHandlers[type] || []) fn({ target });
    },
  };
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 10. non-touch device: install() is a no-op (hasTouch stays false).
{
  const t = makeTouchSandbox({ touch: false });
  assert.equal(t.probe().hasTouch, false);
  assert.equal(t.probe().installed, true);
  assert.deepEqual(Object.keys(t.docHandlers), [], 'no listeners on a non-touch device');
}
// 11. touch device: hasTouch is set (the fork repair) and the trigger arms
//     the panel observer; scans run on the 16/80/200ms schedule.
{
  const t = makeTouchSandbox({ touch: true, panelOpen: true, groupCount: 2 });
  assert.equal(t.probe().hasTouch, true, 'detectTouch() must run at install');
  assert.ok((t.docHandlers.pointerdown || []).length >= 1, 'pointerdown listener armed');
  assert.ok((t.docHandlers.click || []).length >= 1, 'click listener armed');
  // Note: probe() itself queries the effort groups once, so snapshot the
  // counter after the probe calls above and assert the delta.
  const queriesBefore = t.counts.effortQueries;
  await sleep(300);
  assert.equal(t.counts.effortQueries - queriesBefore, 3, 'armPanelObserver schedules 3 scans');
  assert.equal(t.probe().groups, 2);
  assert.equal(t.probe().rows, 6, '3 scans x 2 fresh rows');
}
// 12. debounce: three rapid observer callbacks coalesce into one scan at 80ms.
{
  const t = makeTouchSandbox({ touch: true, panelOpen: true, groupCount: 2 });
  await sleep(300); // let the arming scans finish
  t.counts.effortQueries = 0;
  const obs = t.observerLog.created[0];
  assert.ok(obs, 'an observer must exist after arming');
  obs.cb(); obs.cb(); obs.cb();
  await sleep(50);
  assert.equal(t.counts.effortQueries, 0, 'no scan before the 80ms debounce elapses');
  await sleep(100);
  assert.equal(t.counts.effortQueries, 1, 'three rapid callbacks must coalesce to one scan');
}
// 13. panel closed: scan() zeroes groups and disconnects the observer.
{
  const t = makeTouchSandbox({ touch: true, panelOpen: false, groupCount: 2 });
  t.fireDoc('pointerdown', t.sandbox.document.querySelector('[data-testid="model-selector-trigger"]'));
  await sleep(300);
  assert.equal(t.probe().groups, 0);
  assert.ok(t.observerLog.disconnected >= 1, 'observer must disconnect when the panel is closed');
  assert.equal(t.probe().rows, 0, 'no rows registered while closed');
}

console.log('test_theme_sync_touch_menu.mjs: OK');
