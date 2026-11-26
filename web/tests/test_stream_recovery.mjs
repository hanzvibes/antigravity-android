// test_stream_recovery.mjs - runtime test for the #20 stream-recovery slice.
//
// Loads the three bridge.core fragments involved in the fix
// (online-and-notifications.js, resume-stream-recovery.js, fetch-rewrite.js)
// in a vm sandbox with a stubbed WebView window, then proves the mechanism:
//
//   1. visibilitychange -> visible dispatches online/focus (resume recovery)
//   2. agy:host-resume (dispatched by WebViewLifecycle.resume()) rotates a
//      stuck ConnectRPC stream so its pending read resolves done:true
//      instead of hanging forever (the #20 symptom: stream stuck after
//      switching apps, only fixed by removing the app from Recents)
//   3. loopback streaming RPC URLs are wrapped the same way
//   4. an aborted stream fetch is NOT retried 30x
//   5. non-abort failures still get the startup retry (30 x 120ms)
//   6. 'offline' listeners are dropped and Notification is polyfilled
//      (false "No internet" banner on Tailscale / always-on VPN)
//
// Run: node web/tests/test_stream_recovery.mjs
// (also driven by web/tests/test_stream_recovery.py)

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function assert(cond, msg) {
  if (!cond) throw new Error('assert: ' + msg);
}

function makeEventTarget() {
  const listeners = new Map();
  return {
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(fn);
    },
    removeEventListener(type, fn) {
      if (listeners.has(type)) listeners.get(type).delete(fn);
    },
    dispatchEvent(ev) {
      const type = typeof ev === 'string' ? ev : ev.type;
      for (const fn of [...(listeners.get(type) || [])]) fn(ev);
      return true;
    },
  };
}

const win = makeEventTarget();
win.__dispatched = [];
const origDispatch = win.dispatchEvent.bind(win);
win.dispatchEvent = (ev) => {
  win.__dispatched.push(typeof ev === 'string' ? ev : ev.type);
  return origDispatch(ev);
};

const documentStub = makeEventTarget();
documentStub.visibilityState = 'visible';
win.document = documentStub;
win.setTimeout = setTimeout;
win.clearTimeout = clearTimeout;
win.fetch = origFetchStub;

// --- stubbed network -------------------------------------------------------
let fetchCalls = 0;
let fetchBehavior = 'stream-hang'; // 'stream-hang' | 'abort' | 'fail-twice'

function hangingStream() {
  let sent = false;
  return new ReadableStream({
    pull(controller) {
      if (!sent) {
        sent = true;
        controller.enqueue(new TextEncoder().encode('data: {}\n'));
        return Promise.resolve();
      }
      return new Promise(() => {}); // stuck: never resolves again
    },
  });
}

async function origFetchStub(_url, _opts) {
  fetchCalls++;
  if (fetchBehavior === 'abort') {
    const e = new Error('aborted');
    e.name = 'AbortError';
    throw e;
  }
  if (fetchBehavior === 'fail-twice') {
    if (fetchCalls <= 2) throw new Error('boom');
    return {
      status: 200,
      statusText: 'OK',
      headers: new Headers(),
      body: new ReadableStream({
        start(c) {
          c.enqueue(new TextEncoder().encode('ok'));
          c.close();
        },
      }),
    };
  }
  return { status: 200, statusText: 'OK', headers: new Headers(), body: hangingStream() };
}

// --- sandbox: the fragments share one bundle scope, like bridge.core.js ---
const sandbox = {
  window: null, // set below (window === global in the bundle)
  console: { log: () => {}, warn: () => {}, error: (...a) => console.error(...a) },
  setTimeout,
  clearTimeout,
  Promise,
  AbortController,
  ReadableStream,
  Response,
  Headers,
  Event,
  CustomEvent,
  TextEncoder,
  fetch: origFetchStub,
  coreBase: () => 'http://127.0.0.1:3773',
  appendCsrfQuery: (u) => u,
  ensureCsrf: () => {},
  warn: () => {},
};
sandbox.window = win;
sandbox.global = win;
vm.createContext(sandbox);

for (const f of ['online-and-notifications.js', 'resume-stream-recovery.js', 'fetch-rewrite.js']) {
  vm.runInContext(fs.readFileSync(path.join(root, 'src', 'core', f), 'utf8'), sandbox, { filename: f });
}

const STREAM_URL = 'file://exa.language_server_pb.LanguageServerService/StreamAgentStateUpdates';
const LOOPBACK_STREAM_URL =
  'http://127.0.0.1:3773/exa.language_server_pb.LanguageServerService/StreamAgentStateUpdates';

// 1. visibilitychange -> visible triggers recovery (online + focus).
documentStub.dispatchEvent(new Event('visibilitychange'));
await sleep(400);
assert(win.__dispatched.includes('online'), 'visibilitychange should dispatch online');
assert(win.__dispatched.includes('focus'), 'visibilitychange should dispatch focus');

// 2. agy:host-resume with no active streams is a no-op (but still signals).
win.__dispatched.length = 0;
win.dispatchEvent(new Event('agy:host-resume'));
assert(win.__dispatched.includes('online'), 'host-resume should dispatch online');
assert(win.__dispatched.includes('focus'), 'host-resume should dispatch focus');

// 3. A stuck stream is rotated on host-resume: pending read resolves done.
fetchBehavior = 'stream-hang';
fetchCalls = 0;
const resp = await win.fetch(STREAM_URL, { method: 'POST', headers: {}, body: '{}' });
assert(resp.status === 200, 'stream fetch returns 200');
const reader = resp.body.getReader();
const first = await reader.read();
assert(!first.done && first.value, 'first stream chunk arrives');
let second = null;
const secondPromise = reader.read().then((r) => {
  second = r;
});
await sleep(100);
assert(second === null, 'second read is stuck before resume (reproduces #20)');
win.dispatchEvent(new Event('agy:host-resume'));
await Promise.race([
  secondPromise,
  sleep(2000).then(() => {
    throw new Error('pending stream read never resolved after host-resume');
  }),
]);
assert(second && second.done === true, 'pending read resolves done:true after host-resume');
assert(sandbox.activeStreamClosers.size === 0, 'rotated stream is deregistered');

// 4. Loopback streaming RPC URLs are wrapped the same way.
fetchBehavior = 'stream-hang';
const resp2 = await win.fetch(LOOPBACK_STREAM_URL, { method: 'POST', headers: {}, body: '{}' });
const reader2 = resp2.body.getReader();
const chunk2 = await reader2.read();
assert(!chunk2.done, 'loopback stream delivers chunks');
await reader2.cancel();
assert(sandbox.activeStreamClosers.size === 0, 'cancelled loopback stream is deregistered');

// 5. An aborted stream fetch is NOT retried 30x.
fetchBehavior = 'abort';
fetchCalls = 0;
let threw = null;
try {
  await win.fetch(STREAM_URL, { method: 'POST', headers: {}, body: '{}' });
} catch (e) {
  threw = e;
}
assert(threw && threw.name === 'AbortError', 'abort propagates');
assert(fetchCalls === 1, 'aborted fetch must not be retried, got ' + fetchCalls + ' calls');

// 6. Non-abort failures still get the startup retry.
fetchBehavior = 'fail-twice';
fetchCalls = 0;
await win.fetch('file://exa.language_server_pb.LanguageServerService/GetState', {
  method: 'POST',
  headers: {},
  body: '{}',
});
assert(fetchCalls === 3, 'startup retry still works, got ' + fetchCalls + ' calls');

// 7. 'offline' listeners are dropped; Notification is polyfilled.
let offlineCalled = false;
win.addEventListener('offline', () => {
  offlineCalled = true;
});
win.dispatchEvent(new Event('offline'));
assert(!offlineCalled, "'offline' listeners must be dropped (false banner fix)");
assert(
  win.Notification && win.Notification.permission === 'granted',
  'Notification polyfill present',
);

console.log('test_stream_recovery.mjs: OK');
