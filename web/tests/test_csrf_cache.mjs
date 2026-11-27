// test_csrf_cache.mjs — node harness for the CSRF cookie cache
// (web/src/core/csrf.js, upstream PR #34).
//
// syncCsrf() runs on every RPC (endpoints.js sets the
// x-codeium-csrf-token header from it), so writing both cookies
// unconditionally on each call is redundant once the token is stable.
// The fix caches lastSyncedCookieToken and skips the document.cookie
// writes when the token has not changed.
//
// Proves, with a stubbed document whose cookie setter records writes:
//   1. the first sync writes both cookies;
//   2. a second sync with the same token writes nothing;
//   3. changing the token writes again (and returns the new token);
//   4. readCsrf() prefers CONFIG.csrfToken over the meta tag;
//   5. window.__AG_CSRF__ still wins over CONFIG;
//   6. with nothing set, the fallback token is used.
//
// Run: node web/tests/test_csrf_cache.mjs
// (also driven by web/tests/test_csrf_cache.py)
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const SRC = readFileSync(new URL('../src/core/csrf.js', import.meta.url), 'utf8');

function makeSandbox() {
  const writes = [];
  const document = { querySelector: () => null };
  Object.defineProperty(document, 'cookie', {
    get() { return ''; },
    set(v) { writes.push(v); },
    configurable: true,
  });
  const sandbox = {
    window: {},
    document,
    CONFIG: { csrfToken: undefined, csrf_token: undefined },
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox, { filename: 'csrf.js' });
  return { sandbox, writes };
}

// 1. load runs syncCsrf() once: both cookies written.
const { sandbox, writes } = makeSandbox();
assert.equal(writes.length, 2, `expected 2 cookie writes on load, got ${writes.length}`);
assert.ok(writes[0].startsWith('csrfToken=agy-standalone-token'), writes[0]);
assert.ok(writes[1].startsWith('csrf_token=agy-standalone-token'), writes[1]);

// 2. same token again: no further writes.
sandbox.syncCsrf();
assert.equal(writes.length, 2, `same-token sync must not write cookies, got ${writes.length}`);

// 3. token changes: writes again, returns the new token.
sandbox.CONFIG.csrfToken = 'token-2';
assert.equal(sandbox.syncCsrf(), 'token-2');
assert.equal(writes.length, 4, `changed-token sync must write cookies, got ${writes.length}`);
assert.ok(writes[2].startsWith('csrfToken=token-2'), writes[2]);
assert.ok(writes[3].startsWith('csrf_token=token-2'), writes[3]);
sandbox.syncCsrf();
assert.equal(writes.length, 4, `second sync of token-2 must not write, got ${writes.length}`);

// 4. CONFIG.csrfToken beats the meta tag.
sandbox.document.querySelector = () => ({ getAttribute: () => 'from-meta' });
sandbox.CONFIG.csrfToken = 'from-config';
assert.equal(sandbox.readCsrf(), 'from-config');

// 5. window.__AG_CSRF__ still wins over CONFIG.
sandbox.window.__AG_CSRF__ = 'from-global';
assert.equal(sandbox.readCsrf(), 'from-global');
assert.equal(sandbox.syncCsrf(), 'from-global');
assert.equal(writes.length, 6, `global-token sync must write cookies, got ${writes.length}`);

// 6. fresh sandbox, nothing set: meta tag consulted, fallback otherwise.
const fresh2 = (() => {
  const writes2 = [];
  const document = {
    querySelector: () => ({ getAttribute: () => 'meta-token' }),
  };
  Object.defineProperty(document, 'cookie', {
    get() { return ''; },
    set(v) { writes2.push(v); },
    configurable: true,
  });
  const sb = { window: {}, document, CONFIG: {}, console };
  vm.createContext(sb);
  vm.runInContext(SRC, sb, { filename: 'csrf.js' });
  return { sb, writes2 };
})();
assert.equal(fresh2.sb.readCsrf(), 'meta-token', 'meta tag must be used when no global/config token');
assert.equal(fresh2.writes2.length, 2, 'meta-token load must write both cookies once');

console.log('test_csrf_cache.mjs: OK');
