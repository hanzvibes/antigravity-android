// test_tablet_scale.mjs - runtime test for tablet-scale.js.
//
// Loads the fragment in a vm sandbox with a stubbed window/document and
// proves the zoom steps + the Desktop Mode exclusion + resize handling:
//
//   phone width (390px)       -> no zoom
//   600px                     -> 1.2x
//   800px (10" portrait)      -> 1.3x
//   1280px (tablet landscape) -> 1.4x
//   desktop UA (Antigravity/) -> no zoom at any width (Desktop Mode
//                                already scales via overview mode)
//   resize 390 -> 800 -> 390  -> zoom follows the width
//
// Run: node web/tests/test_tablet_scale.mjs
// (also driven by web/tests/test_tablet_scale.py)

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = fs.readFileSync(
  path.join(root, 'src', 'patches', 'web_optimizations', 'tablet-scale.js'),
  'utf8',
);

const MOBILE_UA =
  'Mozilla/5.0 (Linux; Android 17; Pixel 10 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36';
const DESKTOP_UA =
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Antigravity/2.4.1';

function assert(cond, msg) {
  if (!cond) throw new Error('assert: ' + msg);
}

function makeEnv(width, ua) {
  const listeners = {};
  const win = {
    innerWidth: width,
    navigator: { userAgent: ua },
    addEventListener(type, fn) {
      listeners[type] = fn;
    },
    dispatchResize() {
      if (listeners.resize) listeners.resize();
    },
  };
  const documentStub = { documentElement: { style: {} } };
  const sandbox = { window: win, console };
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox, { filename: 'tablet-scale.js' });
  sandbox.installTabletScale(win, documentStub);
  return { win, style: documentStub.documentElement.style };
}

// 1. Phone widths: no zoom.
let env = makeEnv(390, MOBILE_UA);
assert(!env.style.zoom, 'phone 390px must not zoom, got ' + env.style.zoom);
env = makeEnv(599, MOBILE_UA);
assert(!env.style.zoom, '599px must not zoom, got ' + env.style.zoom);

// 2. Tablet steps.
env = makeEnv(600, MOBILE_UA);
assert(env.style.zoom === '1.2', '600px must zoom 1.2x, got ' + env.style.zoom);
env = makeEnv(800, MOBILE_UA);
assert(env.style.zoom === '1.3', '800px must zoom 1.3x, got ' + env.style.zoom);
env = makeEnv(1280, MOBILE_UA);
assert(env.style.zoom === '1.4', '1280px must zoom 1.4x, got ' + env.style.zoom);

// 3. Desktop Mode UA: never zoom, even on a wide tablet.
env = makeEnv(1280, DESKTOP_UA);
assert(!env.style.zoom, 'desktop UA must not zoom, got ' + env.style.zoom);

// 4. Resize follows the width (rotation / split-screen).
env = makeEnv(390, MOBILE_UA);
assert(!env.style.zoom, 'starts unzoomed at 390px');
env.win.innerWidth = 800;
env.win.dispatchResize();
assert(env.style.zoom === '1.3', 'resize to 800px must zoom 1.3x, got ' + env.style.zoom);
env.win.innerWidth = 390;
env.win.dispatchResize();
assert(!env.style.zoom, 'resize back to 390px must clear zoom, got ' + env.style.zoom);

console.log('test_tablet_scale.mjs: OK');
