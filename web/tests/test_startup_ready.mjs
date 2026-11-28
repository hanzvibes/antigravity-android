// test_startup_ready.mjs — node harness for the startup_ready slice ported
// from upstream PR #34.
//
// Startup ready (web/src/patches/startup_ready/*) tells the native side
// the web UI has really rendered, so Android.onUiReady fires at the right
// moment instead of on a fixed timeout. It signals on any of:
//   - a '[ConversationLoad]' console.info (console-hook.js),
//   - real chat content / the input area / any root content
//     (detect-ui.js, watched by arm.js via MutationObserver + 40ms poller),
//   - a 5.5s fallback timeout.
// The head changes ported here: console-hook.js only signals while
// !state.signalled and unhooks itself (console.info = origInfo) once the
// UI is ready; detect-ui.js uses the current Antigravity selectors
// ([data-testid="conversation-view"], [data-testid="autoscroll-viewport"],
// [role="article"], [data-lexical-editor="true"]) instead of the old
// [data-role]/[data-turn-id] ones.
//
// Run: node web/tests/test_startup_ready.mjs
// (also driven by web/tests/test_startup_ready.py)
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const WEB = new URL('..', import.meta.url);
const read = (rel) => readFileSync(new URL(rel, WEB), 'utf8');

const FRAGS = [
  'src/patches/startup_ready/signal.js',
  'src/patches/startup_ready/error-capture.js',
  'src/patches/startup_ready/console-hook.js',
  'src/patches/startup_ready/detect-ui.js',
  'src/patches/startup_ready/arm.js',
  'src/patches/startup_ready/public-api.js',
];

// ---------------------------------------------------------------- fake clock
// Deterministic timers: arm() uses a 40ms poller and a 5.5s fallback, so a
// virtual clock keeps the tests instant instead of waiting real seconds.
function makeClock() {
  let now = 0;
  let nextId = 0;
  const timers = new Map();
  return {
    setTimeout: (fn, ms) => { const h = ++nextId; timers.set(h, { fn, at: now + (ms || 0), iv: 0 }); return h; },
    setInterval: (fn, ms) => { const h = ++nextId; timers.set(h, { fn, at: now + (ms || 0), iv: ms || 0 }); return h; },
    clearTimeout: (h) => timers.delete(h),
    clearInterval: (h) => timers.delete(h),
    tick(ms) {
      const end = now + ms;
      for (;;) {
        let next = null;
        for (const [h, t] of timers) {
          if (t.at <= end && (!next || t.at < next.t.at)) next = { h, t };
        }
        if (!next) break;
        now = next.t.at;
        if (next.t.iv) next.t.at = now + next.t.iv;
        else timers.delete(next.h);
        next.t.fn();
      }
      now = end;
    },
  };
}

// ---------------------------------------------------------------- fake DOM
function fakeEl(name) {
  return { __name: name };
}

function fakeRoot(present = [], hasChildren = false) {
  return {
    __name: 'root',
    querySelector: (sel) => {
      const parts = sel.split(',').map((s) => s.trim());
      return parts.some((p) => present.includes(p)) ? fakeEl('match') : null;
    },
    firstElementChild: hasChildren ? fakeEl('child') : null,
    children: hasChildren ? [fakeEl('child')] : [],
  };
}

function makeSandbox(opts = {}) {
  const {
    readyState = 'complete',
    rootPresent = [],
    rootChildren = false,
    hasRoot = true,
    android = true,
  } = opts;
  const clock = makeClock();
  const logs = { log: [], info: [], warn: [], error: [] };
  const fakeConsole = {
    log: (...a) => logs.log.push(a.join(' ')),
    info: (...a) => logs.info.push(a.join(' ')),
    warn: (...a) => logs.warn.push(a.join(' ')),
    error: (...a) => logs.error.push(a.join(' ')),
  };
  const origInfo = fakeConsole.info;
  const androidCalls = { onUiReady: [], onUiError: [] };
  const observers = [];
  class MutationObserver {
    constructor(cb) { this.cb = cb; observers.push(this); this.disconnected = 0; }
    observe() {}
    disconnect() { this.disconnected++; }
  }
  const docListeners = {};
  let root = hasRoot ? fakeRoot(rootPresent, rootChildren) : null;
  const document = {
    readyState,
    getElementById: (id) => (id === 'root' ? root : null),
    body: fakeEl('body'),
    documentElement: fakeEl('html'),
    addEventListener: (type, fn) => { (docListeners[type] ||= []).push(fn); },
  };
  const winListeners = {};
  const window = {
    document,
    MutationObserver,
    __AG_NATIVE_BRIDGE_TOKEN__: 'tok-1',
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    setInterval: clock.setInterval,
    clearInterval: clock.clearInterval,
    addEventListener: (type, fn) => { (winListeners[type] ||= []).push(fn); },
  };
  if (android) {
    window.Android = {
      onUiReady: (tok) => androidCalls.onUiReady.push(tok),
      onUiError: (tok, msg) => androidCalls.onUiError.push([tok, msg]),
    };
  }
  // Bare MutationObserver: the fragments call `new MutationObserver(...)`
  // without the window. prefix (in a WebView window IS the global scope).
  const sandbox = { window, document, console: fakeConsole, MutationObserver };
  vm.createContext(sandbox);
  const src = FRAGS.map(read).join('\n');
  vm.runInContext('(function(){\n' + src + '\n})();', sandbox, { filename: 'startup_ready.js' });
  // The fragment wraps console.info at load: capture the wrapper so the
  // tests can tell it apart from the restored original. (The restored
  // value is console.info.bind(console), a new bound function each time,
  // so identity against the pre-load function is not the right check —
  // what matters is the wrapper is gone and logging goes direct.)
  const wrapperInfo = fakeConsole.info;
  return {
    sandbox, clock, logs, androidCalls, observers, docListeners, winListeners,
    fakeConsole, origInfo, wrapperInfo,
    installed: () => sandbox.window.__agStartupReady && sandbox.window.__agStartupReady.__installed,
    setRoot: (present, children = false) => { root = fakeRoot(present, children); },
    fireDoc: (type) => { for (const fn of docListeners[type] || []) fn(); },
    fireWin: (type, ev) => { for (const fn of winListeners[type] || []) fn(ev); },
    reasons: () => logs.log.filter((m) => m.startsWith('[AGY Startup] UI Ready triggered via: ')),
  };
}

// 1. A '[ConversationLoad]' console.info signals once and unhooks the hook.
{
  const t = makeSandbox();
  assert.equal(t.installed(), true);
  assert.equal(t.fakeConsole.info, t.wrapperInfo, 'hook must be installed at load');
  t.sandbox.console.info('[ConversationLoad] finished in 123ms');
  assert.deepEqual(t.androidCalls.onUiReady, ['tok-1']);
  assert.deepEqual(t.reasons(), ['[AGY Startup] UI Ready triggered via: conversation-load-completed']);
  assert.notEqual(t.fakeConsole.info, t.wrapperInfo, 'console.info must be restored after signalling');
  t.sandbox.console.info('[ConversationLoad] again');
  assert.equal(t.androidCalls.onUiReady.length, 1, 'must not signal twice');
  assert.equal(t.logs.info.length, 2, 'restored info still logs');
}
// 2. A non-matching console.info neither signals nor unhooks.
{
  const t = makeSandbox();
  t.sandbox.console.info('some other log line');
  assert.equal(t.androidCalls.onUiReady.length, 0);
  assert.equal(t.fakeConsole.info, t.wrapperInfo, 'hook must stay installed while waiting');
}
// 3. Already signalled via detect-ui: a later [ConversationLoad] restores
//    console.info without a second onUiReady.
{
  const t = makeSandbox({ rootPresent: ['[data-testid="conversation-view"]'] });
  assert.equal(t.androidCalls.onUiReady.length, 1, 'detect-ui must signal at load');
  t.sandbox.console.info('[ConversationLoad] late');
  assert.notEqual(t.fakeConsole.info, t.wrapperInfo, 'hook must unhook once already signalled');
  assert.equal(t.androidCalls.onUiReady.length, 1);
}
// 4. detect-ui: the new conversation selectors signal 'messages-rendered'.
{
  const t = makeSandbox({ rootPresent: ['[data-testid="autoscroll-viewport"]'] });
  assert.equal(t.androidCalls.onUiReady.length, 1);
  assert.deepEqual(t.reasons(), ['[AGY Startup] UI Ready triggered via: messages-rendered']);
}
// 5. detect-ui: the OLD selectors no longer match — a root that only has
//    [data-role="user"] content and no children/input must not signal.
{
  const t = makeSandbox({ rootPresent: ['[data-role="user"]', '[data-turn-id]', '.message-row', '[data-message-id]'] });
  assert.equal(t.androidCalls.onUiReady.length, 0, 'old selectors must not trigger the ready signal');
  t.clock.tick(6000);
  assert.equal(t.androidCalls.onUiReady.length, 1, 'only the 5.5s fallback may signal');
  assert.deepEqual(t.reasons(), ['[AGY Startup] UI Ready triggered via: fallback-timeout']);
}
// 6. detect-ui: the Lexical editor counts as the input area.
{
  const t = makeSandbox({ rootPresent: ['[data-lexical-editor="true"]'] });
  assert.equal(t.androidCalls.onUiReady.length, 1);
  assert.deepEqual(t.reasons(), ['[AGY Startup] UI Ready triggered via: chat-input-ready']);
}
// 7. detect-ui: any root content (no messages, no input) signals
//    'root-has-content'.
{
  const t = makeSandbox({ rootChildren: true });
  assert.equal(t.androidCalls.onUiReady.length, 1);
  assert.deepEqual(t.reasons(), ['[AGY Startup] UI Ready triggered via: root-has-content']);
}
// 8. detect-ui: no #root at all signals nothing (until the fallback).
{
  const t = makeSandbox({ hasRoot: false });
  assert.equal(t.androidCalls.onUiReady.length, 0);
  t.clock.tick(5500);
  assert.equal(t.androidCalls.onUiReady.length, 1);
  assert.deepEqual(t.reasons(), ['[AGY Startup] UI Ready triggered via: fallback-timeout']);
}
// 9. arm(): the 40ms poller picks up content that appears after load, then
//    stops; the later fallback fires harmlessly without a second signal.
{
  const t = makeSandbox();
  assert.equal(t.androidCalls.onUiReady.length, 0);
  t.clock.tick(40);
  assert.equal(t.androidCalls.onUiReady.length, 0, 'empty root must not signal on a poll tick');
  t.setRoot(['[role="article"]']);
  t.clock.tick(40);
  assert.equal(t.androidCalls.onUiReady.length, 1);
  assert.deepEqual(t.reasons(), ['[AGY Startup] UI Ready triggered via: messages-rendered']);
  t.clock.tick(6000);
  assert.equal(t.androidCalls.onUiReady.length, 1, 'fallback must not signal twice');
}
// 10. arm(): the MutationObserver path signals and disconnects the observer.
{
  const t = makeSandbox();
  assert.equal(t.observers.length, 1, 'arm() must observe the root');
  t.setRoot(['.prose']);
  t.observers[0].cb();
  assert.equal(t.androidCalls.onUiReady.length, 1);
  assert.equal(t.observers[0].disconnected, 1);
  t.clock.tick(6000);
  assert.equal(t.androidCalls.onUiReady.length, 1);
}
// 11. arm(): the 5.5s fallback fires exactly at 5500ms on an empty root.
{
  const t = makeSandbox();
  t.clock.tick(5499);
  assert.equal(t.androidCalls.onUiReady.length, 0);
  t.clock.tick(1);
  assert.equal(t.androidCalls.onUiReady.length, 1);
  assert.deepEqual(t.reasons(), ['[AGY Startup] UI Ready triggered via: fallback-timeout']);
}
// 12. error-capture: a startup error reaches Android.onUiError, but only
//     while the UI has not signalled ready yet.
{
  const t = makeSandbox();
  t.fireWin('error', { message: 'boom', filename: 'app.js', lineno: 3, colno: 4 });
  assert.equal(t.androidCalls.onUiError.length, 1);
  assert.ok(t.androidCalls.onUiError[0][1].includes('[JS Error app.js:3:4] boom'));
  assert.ok(t.logs.error.some((m) => m.includes('[JS Error app.js:3:4] boom')));
  t.fireWin('unhandledrejection', { reason: { stack: 'rejected!' } });
  assert.equal(t.androidCalls.onUiError.length, 2);
  assert.ok(t.androidCalls.onUiError[1][1].includes('[Unhandled Rejection] rejected!'));
  t.sandbox.console.info('[ConversationLoad] done');
  assert.equal(t.androidCalls.onUiReady.length, 1, 'signalled now');
  t.fireWin('error', { message: 'late boom' });
  assert.equal(t.androidCalls.onUiError.length, 2, 'no onUiError after the ready signal');
  assert.ok(t.logs.error.some((m) => m.includes('late boom')), 'the error is still logged');
}
// 13. readyState 'loading': arm() waits for DOMContentLoaded, then works.
{
  const t = makeSandbox({ readyState: 'loading' });
  assert.equal(t.observers.length, 0, 'must not arm before DOMContentLoaded');
  t.fireDoc('DOMContentLoaded');
  assert.equal(t.observers.length, 1, 'must arm on DOMContentLoaded');
  t.setRoot(['textarea']);
  t.clock.tick(40);
  assert.equal(t.androidCalls.onUiReady.length, 1);
  assert.deepEqual(t.reasons(), ['[AGY Startup] UI Ready triggered via: chat-input-ready']);
}

console.log('test_startup_ready.mjs: OK');
