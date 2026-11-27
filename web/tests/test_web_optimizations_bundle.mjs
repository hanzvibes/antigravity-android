// test_web_optimizations_bundle.mjs — node harness for the upstream
// PR #34 web_optimizations bundle.js port.
//
// bundle.js (upstream PR #34) consolidates the old taps/viewport/gpu
// fragments into one file and adds: the Base UI fast-path flag, passive
// scroll listeners + blocking the desktop overlay-scrollbar listeners,
// a soft-keyboard focus guard, a lazy 48kHz AudioContext gate, and
// targeted CSS (instant taps/menus, native scrollbar, no backdrop
// blur, no Prism text-shadow). tablet-scale.js (ours) self-installs
// after it.
//
// Runs both fragments in manifest order inside a vm context with a
// stubbed window/document, and proves:
//   1. BASE_UI_ANIMATIONS_DISABLED is set (the main.js fast-path).
//   2. One style tag (data-agy="web-optimizations") is injected with
//      the instant-tap / overlay-scrollbar / no-blur CSS and no
//      translateZ(0) (upstream deliberately avoids it).
//   3. Scroll listeners default to passive:true.
//   4. A document scroll listener whose source mentions
//      .md-table-scroll is blocked.
//   5. The focus guard blocks editor focus before any user tap,
//      allows it after a tap, and blocks it again right after a
//      popup/menu tap (700ms window).
//   6. The audio gate suspends 48kHz boot voice contexts only, and
//      defers audioWorklet.addModule until resume().
//   7. tablet-scale.js scales the viewport meta at 800px -> 1.3x.
//
// Run: node web/tests/test_web_optimizations_bundle.mjs
// (also driven by web/tests/test_web_optimizations_bundle.py)
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const BUNDLE = readFileSync(new URL('../src/patches/web_optimizations/bundle.js', import.meta.url), 'utf8');
const TABLET = readFileSync(new URL('../src/patches/web_optimizations/tablet-scale.js', import.meta.url), 'utf8');

// --- stubs ------------------------------------------------------------
const origAddCalls = [];
function EventTarget() {}
EventTarget.prototype.addEventListener = function (type, listener, options) {
  origAddCalls.push({ target: this, type, listener, options });
};

const focusCalls = [];
function HTMLElement() {}
HTMLElement.prototype.focus = function (options) {
  focusCalls.push({ el: this, options });
};

function OrigAudioContext(opts) {
  this.opts = opts;
  this.state = 'running';
  this.suspended = false;
  this.resumeCalls = 0;
  this.addModuleCalls = [];
  const self = this;
  this.audioWorklet = {
    addModule(url, o) {
      self.addModuleCalls.push([url, o]);
      return Promise.resolve();
    },
  };
}
OrigAudioContext.prototype.suspend = function () {
  this.suspended = true;
  return Promise.resolve();
};
OrigAudioContext.prototype.resume = function () {
  this.resumeCalls++;
  return Promise.resolve();
};
OrigAudioContext.prototype.createMediaStreamSource = function (s) {
  return { stream: s };
};

const appendedStyles = [];
const docListeners = [];
const meta = {
  _content: 'width=device-width, initial-scale=1.0, viewport-fit=cover, maximum-scale=1.0',
  getAttribute(k) { return k === 'content' ? this._content : null; },
  setAttribute(k, v) { if (k === 'content') this._content = v; },
};
const documentStub = {
  querySelector(sel) { return sel === 'meta[name="viewport"]' ? meta : null; },
  querySelectorAll() { return []; },
  createElement(tag) {
    if (tag !== 'style') return {};
    const el = {
      attrs: {},
      _text: '',
      setAttribute(k, v) { this.attrs[k] = v; },
      get textContent() { return this._text; },
      set textContent(v) { this._text = v; },
    };
    return el;
  },
  head: { appendChild(el) { appendedStyles.push(el); } },
  documentElement: { style: { setProperty() {} } },
  addEventListener(type, fn, opts) { docListeners.push({ type, fn, opts }); },
};

const winListeners = [];
const windowStub = {
  document: documentStub,
  navigator: { userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36' },
  innerWidth: 800,
  addEventListener(type, fn, opts) { winListeners.push({ type, fn, opts }); },
  EventTarget,
  HTMLElement,
  AudioContext: OrigAudioContext,
};

const sandbox = { window: windowStub, console };
vm.createContext(sandbox);
// The bundler concatenates the fragments inside one IIFE (the
// fragments use top-level `return` for their install guards), so run
// them the same way: one IIFE, manifest order.
vm.runInContext(`(function(){\n${BUNDLE}\n${TABLET}\n})();`, sandbox, { filename: 'web_optimizations.js' });

// 1. Base UI fast-path flag + public API.
assert.equal(windowStub.BASE_UI_ANIMATIONS_DISABLED, true);
assert.equal(windowStub.__agWebOptimizations.installed, true);
assert.equal(windowStub.__agWebOptimizations.version, '3.2.0');

// 2. One injected style tag with the perf CSS, no translateZ(0).
assert.equal(appendedStyles.length, 1, `expected 1 style tag, got ${appendedStyles.length}`);
const style = appendedStyles[0];
assert.equal(style.attrs['data-agy'], 'web-optimizations');
assert.ok(style.textContent.includes('touch-action: manipulation'), 'missing instant-tap CSS');
assert.ok(style.textContent.includes('overlay-scrollbar'), 'missing overlay-scrollbar CSS');
assert.ok(style.textContent.includes('backdrop-filter: none'), 'missing no-blur CSS');
assert.ok(!style.textContent.includes('translateZ(0)'), 'bundle.js must not use translateZ(0)');

// 3. Scroll listeners default to passive:true.
const patchedAdd = windowStub.EventTarget.prototype.addEventListener;
const dummyTarget = {};
patchedAdd.call(dummyTarget, 'scroll', function onScroll() {});
assert.equal(origAddCalls.length, 1);
assert.equal(origAddCalls[0].options.passive, true);
assert.equal(origAddCalls[0].options.capture, false);
patchedAdd.call(dummyTarget, 'scroll', function onScroll2() {}, { capture: true });
assert.equal(origAddCalls[1].options.passive, true);
assert.equal(origAddCalls[1].options.capture, true);

// 4. Desktop overlay-scrollbar document scroll listener is blocked.
function mdTableFn() { /* .md-table-scroll */ }
const before = origAddCalls.length;
patchedAdd.call(documentStub, 'scroll', mdTableFn);
assert.equal(origAddCalls.length, before, 'md-table-scroll listener must be blocked');

// 5. Focus guard: blocked before any tap, allowed after a tap,
//    blocked again right after a popup/menu tap.
const editor = {
  isContentEditable: true,
  getAttribute(k) { return k === 'contenteditable' ? 'true' : null; },
  hasAttribute(k) { return k === 'data-lexical-editor'; },
};
const guardedFocus = windowStub.HTMLElement.prototype.focus;
guardedFocus.call(editor);
assert.equal(focusCalls.length, 0, 'editor focus before any tap must be blocked');
const tapEntry = docListeners.find((l) => l.type === 'pointerdown');
assert.ok(tapEntry, 'recordTap pointerdown listener missing');
tapEntry.fn({ target: { closest: () => null } });
guardedFocus.call(editor);
assert.equal(focusCalls.length, 1, 'editor focus after a tap must be allowed');
assert.equal(focusCalls[0].options.preventScroll, true);
const popupEl = { contains: () => false };
tapEntry.fn({
  target: { closest: (sel) => (sel.includes('model-selector') ? popupEl : null) },
});
guardedFocus.call(editor);
assert.equal(focusCalls.length, 1, 'editor focus right after a popup tap must be blocked');

// 6. Audio gate: 48kHz boot context suspended, normal context untouched;
//    addModule deferred until resume().
const Wrapped = windowStub.AudioContext;
const c48 = new Wrapped({ sampleRate: 48000 });
assert.equal(c48.suspended, true, '48kHz boot context must be suspended');
const cNormal = new Wrapped();
assert.equal(cNormal.suspended, false, 'normal context must not be suspended');
c48.audioWorklet.addModule('worklet.js');
assert.equal(c48.addModuleCalls.length, 0, 'addModule must be deferred until resume()');
await c48.resume();
assert.equal(c48.addModuleCalls.length, 1, 'resume() must flush the deferred addModule');
assert.equal(c48.addModuleCalls[0][0], 'worklet.js');

// 7. tablet-scale.js: 800px device width -> 1.3x meta.
assert.equal(
  meta._content,
  'width=615, initial-scale=1.3, viewport-fit=cover, maximum-scale=1.3',
  `unexpected meta content: ${meta._content}`,
);

console.log('test_web_optimizations_bundle.mjs: OK');
