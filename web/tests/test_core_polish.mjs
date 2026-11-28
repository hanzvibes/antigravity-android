// test_core_polish.mjs — node harness for the core-polish leftovers ported
// from upstream PR #34 (namespace.js VERSION bump + public-api.js exposing
// the stream-recovery functions on window.__agBridgeCore).
//
// What this change is: the last small core-polish diffs of upstream PR #34
// that belonged to no named slice (PR #13 deliberately left them out):
//   - web/src/core/namespace.js: VERSION '1.0.0' -> '1.2.1' (flows into
//     api.version and CONFIG appVersion/version via config.js).
//   - web/src/core/public-api.js: window.__agBridgeCore now also exposes
//     triggerStreamRecovery and getActiveStreamCount (the latter returns
//     activeStreamClosers.size), and the ready log line is versioned:
//     "v1.2.1 ready (loopback stream recovery + online shim active)".
// The functions themselves were already defined in the fork (PR #4 ported
// resume-stream-recovery.js byte-identical); they just were not exposed.
//
// The harness runs the nine bridge.core fragments in manifest order inside
// one IIFE in a vm context with stubbed window/document/fetch, then drives
// the public API the way the app would: register a loopback streaming RPC
// via the wrapped fetch, watch the active-stream count go 0 -> 1, and
// rotate it away with triggerStreamRecovery (directly and via the real
// 'agy:host-resume' listener).
//
// Run: node web/tests/test_core_polish.mjs
// (also driven by web/tests/test_core_polish.py)
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const WEB = new URL('..', import.meta.url);
const read = (rel) => readFileSync(new URL(rel, WEB), 'utf8');

const FRAGS = [
  'src/core/namespace.js',
  'src/core/online-and-notifications.js',
  'src/core/polyfills-process.js',
  'src/core/config.js',
  'src/core/csrf.js',
  'src/core/endpoints.js',
  'src/core/resume-stream-recovery.js',
  'src/core/fetch-rewrite.js',
  'src/core/public-api.js',
];

const STREAM_URL =
  'https://127.0.0.1:45157/exa.language_server_pb.LanguageServerService/StreamAgentStateUpdates';

function makeSandbox() {
  const logs = { log: [], info: [], warn: [], error: [] };
  const fakeConsole = {
    log: (...a) => logs.log.push(a.join(' ')),
    info: (...a) => logs.info.push(a.join(' ')),
    warn: (...a) => logs.warn.push(a.join(' ')),
    error: (...a) => logs.error.push(a.join(' ')),
  };
  const winListeners = {};
  const docListeners = {};
  const dispatched = [];
  const document = {
    cookie: '',
    visibilityState: 'visible',
    querySelector: () => null,
    addEventListener: (type, fn) => { (docListeners[type] ||= []).push(fn); },
  };
  const window = {
    document,
    location: { search: '' },
    addEventListener: (type, fn) => { (winListeners[type] ||= []).push(fn); },
    dispatchEvent: (ev) => { dispatched.push(ev && ev.type); return true; },
    fetch: () => Promise.resolve({}),
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
  };
  const sandbox = {
    window,
    document,
    console: fakeConsole,
    // node vm contexts lack several WHATWG globals the fragments use.
    URLSearchParams,
    Headers,
    AbortController,
    Event,
    ReadableStream,
    Response,
    atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    queueMicrotask,
  };
  vm.createContext(sandbox);
  const src = FRAGS.map(read).join('\n');
  vm.runInContext('(function(){\n' + src + '\n})();', sandbox, { filename: 'bridge.core.js' });
  return {
    sandbox, logs, winListeners, docListeners, dispatched,
    api: () => sandbox.window.__agBridgeCore,
    fireWin: (type) => { for (const fn of winListeners[type] || []) fn(); },
  };
}

// 1. The API object exists and carries the bumped version everywhere.
{
  const t = makeSandbox();
  const api = t.api();
  assert.ok(api, 'window.__agBridgeCore must exist');
  assert.equal(api.version, '1.2.1');
  assert.equal(api.config.version, '1.2.1');
  assert.equal(api.config.appVersion, '1.2.1');
  assert.equal(t.sandbox.window.__APP_CONFIG__.version, '1.2.1');
  assert.ok(
    t.logs.log.some((m) => m.includes("[AGY bridge.core] v1.2.1 ready (loopback stream recovery + online shim active)")),
    'ready log must be the versioned head line, got: ' + JSON.stringify(t.logs.log),
  );
  assert.ok(
    !t.logs.log.some((m) => m.includes('ready (endpoints:')),
    'the old endpoints-count log line must be gone',
  );
}

// 2. The stream-recovery functions are exposed and callable.
{
  const t = makeSandbox();
  const api = t.api();
  assert.equal(typeof api.triggerStreamRecovery, 'function');
  assert.equal(typeof api.getActiveStreamCount, 'function');
  assert.equal(api.getActiveStreamCount(), 0, 'no streams at load');
}

// 3. A loopback streaming RPC registered via the wrapped fetch shows up
//    in the count, and triggerStreamRecovery rotates it away.
{
  const t = makeSandbox();
  const api = t.api();
  await t.sandbox.window.fetch(STREAM_URL);
  assert.equal(api.getActiveStreamCount(), 1, 'one active stream after the fetch');
  api.triggerStreamRecovery('manual-test', true);
  assert.equal(api.getActiveStreamCount(), 0, 'recovery must close the stream');
  assert.ok(
    t.logs.log.some((m) => m.includes('manual-test: rotating 1 active stream(s)')),
    'rotation must be logged, got: ' + JSON.stringify(t.logs.log),
  );
  assert.ok(t.dispatched.includes('online'), 'recovery must dispatch online');
  assert.ok(t.dispatched.includes('focus'), 'recovery must dispatch focus');
}

// 4. The 300ms debounce: a non-forced trigger right after a forced one
//    dispatches nothing more.
{
  const t = makeSandbox();
  const api = t.api();
  api.triggerStreamRecovery('first', true);
  const dispatchedAfterFirst = t.dispatched.length;
  api.triggerStreamRecovery('second', false);
  assert.equal(t.dispatched.length, dispatchedAfterFirst, 'debounced trigger must be a no-op');
}

// 5. The real 'agy:host-resume' listener rotates open streams.
{
  const t = makeSandbox();
  const api = t.api();
  assert.ok((t.winListeners['agy:host-resume'] || []).length >= 1, 'host-resume listener must be registered');
  await t.sandbox.window.fetch(STREAM_URL);
  assert.equal(api.getActiveStreamCount(), 1);
  t.fireWin('agy:host-resume');
  assert.equal(api.getActiveStreamCount(), 0, 'host-resume must rotate the stream');
  assert.ok(
    t.logs.log.some((m) => m.includes('agy:host-resume: rotating 1 active stream(s)')),
    'host-resume rotation must be logged',
  );
}

// 6. A forced trigger with no open streams does not throw and still
//    dispatches online/focus.
{
  const t = makeSandbox();
  const api = t.api();
  api.triggerStreamRecovery('empty', true);
  assert.equal(api.getActiveStreamCount(), 0);
  assert.ok(t.dispatched.includes('online'));
  assert.ok(t.dispatched.includes('focus'));
}

// 7. A non-streaming fetch does not register a stream.
{
  const t = makeSandbox();
  const api = t.api();
  await t.sandbox.window.fetch('https://example.com/foo');
  assert.equal(api.getActiveStreamCount(), 0, 'plain https fetch must not register');
}

console.log('test_core_polish.mjs: OK');
