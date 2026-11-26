(function(){
/**
 * patches/web_optimizations/taps.js - kill the 300ms double-tap delay.
 */
'use strict';

function installTaps(doc) {
  try {
    var style = doc.createElement('style');
    style.setAttribute('data-agy', 'web-optimizations');
    style.textContent =
      'button,a,[role="button"],input,select,textarea{touch-action:manipulation;}';
    (doc.head || doc.documentElement).appendChild(style);
  } catch (e) {}
}

/**
 * patches/web_optimizations/viewport.js - keep --agy-vvh honest while the
 * soft keyboard opens.
 */
function installViewport(global, doc) {
  try {
    if (global.visualViewport) {
      global.visualViewport.addEventListener('resize', function () {
        var vv = global.visualViewport;
        if (vv && vv.height && doc.documentElement) {
          doc.documentElement.style.setProperty(
            '--agy-vvh', Math.round(vv.height) + 'px');
        }
      }, { passive: true });
    }
  } catch (e) {}
}

/**
 * patches/web_optimizations/tablet-scale.js - scale the whole UI up on
 * tablets, where the phone-density web UI otherwise renders tiny.
 *
 * The Antigravity web UI is laid out for phone-width viewports at 100%:
 * on a tablet the same CSS sizes (text, buttons, everything) feel small
 * against the big screen, and there is no text-size setting in the app
 * to fix it. CSS `zoom` on the root element scales the entire layout
 * uniformly — unlike WebSettings text zoom, which only scales text —
 * and the page re-flows at the zoomed size, so nothing overflows.
 *
 * Scale steps by layout-viewport width (CSS px):
 *   < 600px (phones)   -> no scaling
 *   600-699px          -> 1.2x  (small tablets, portrait)
 *   700-899px          -> 1.3x  (10" tablets, portrait)
 *   >= 900px           -> 1.4x  (tablets, landscape)
 * Recomputed on resize, so rotation and split-screen adapt.
 *
 * Desktop Mode is excluded on purpose: it already scales the page
 * (wide viewport + overview mode), and its desktop UA carries the
 * `Antigravity/` token — applying zoom on top would double-scale.
 */
function installTabletScale(global, doc) {
  try {
    var el = doc && doc.documentElement;
    if (!el || !el.style) return;

    var ua = '';
    try {
      ua = (global.navigator && global.navigator.userAgent) || '';
    } catch (e) {}
    if (ua.indexOf('Antigravity/') !== -1) return;

    function layoutWidth() {
      try {
        return global.innerWidth || 0;
      } catch (e) {
        return 0;
      }
    }

    function scaleFor(w) {
      if (w >= 900) return 1.4;
      if (w >= 700) return 1.3;
      if (w >= 600) return 1.2;
      return 1;
    }

    function apply() {
      var s = scaleFor(layoutWidth());
      el.style.zoom = s > 1 ? String(s) : '';
    }

    apply();
    try {
      global.addEventListener('resize', apply, { passive: true });
    } catch (e) {}
  } catch (e) {}
}

/**
 * patches/web_optimizations/gpu.js - GPU-accelerate scroll/animation surfaces
 * and isolate layout for lists.
 */
function installGpu(doc) {
  try {
    if (!doc.querySelector('style[data-agy="gpu-acceleration"]')) {
      var gpu = doc.createElement('style');
      gpu.setAttribute('data-agy', 'gpu-acceleration');
      // Promote ONLY the real scroll containers. Never inline <code>/<pre>:
      // per-element layers explode on Mali and saturate RenderThread.
      gpu.textContent =
        'main, [data-testid="chat-container"], .scrollable {' +
        ' transform: translateZ(0);' +
        ' -webkit-overflow-scrolling: touch; }' +
        '[role="listitem"], .message-row, .artifact-viewer {' +
        ' contain: layout style; }' +
        '*{ -webkit-tap-highlight-color: transparent; }';
      (doc.head || doc.documentElement).appendChild(gpu);
    }
  } catch (e) {}
}

/**
 * patches/web_optimizations/public-api.js - install and expose.
 */
var global = window;

if (global.__AG_WEB_OPTIMIZATIONS__) return;
global.__AG_WEB_OPTIMIZATIONS__ = true;

var doc = global.document;
if (!doc) return;

installTaps(doc);
installViewport(global, doc);
installTabletScale(global, doc);
installGpu(doc);

global.__agWebOptimizations = { installed: true };


})();
