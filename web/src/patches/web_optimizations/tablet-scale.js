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
