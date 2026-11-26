/**
 * patches/web_optimizations/tablet-scale.js - scale the whole UI up on
 * tablets, where the phone-density web UI otherwise renders tiny.
 *
 * The Antigravity web UI is laid out for phone-width viewports at 100%:
 * on a tablet the same CSS sizes (text, buttons, everything) feel small
 * against the big screen, and there is no text-size setting in the app
 * to fix it.
 *
 * HOW IT SCALES (and what PR #6 got wrong): PR #6 applied CSS `zoom` on
 * the root element, assuming the page would re-flow at the zoomed size.
 * It does not, in this WebView: root zoom magnifies the rendered page
 * from the top-left without shrinking the layout viewport, so centered
 * content shifts right and the right side clips. On the user's tablet
 * (640 CSS px wide) the welcome screen landed centered at ~60% of the
 * screen instead of 50%, with its card cut off on the right.
 *
 * So this fragment narrows the LAYOUT VIEWPORT itself, through the
 * viewport meta tag: `width=<deviceWidth / z>, initial-scale=<z>`. The
 * browser then lays the page out at the narrower width and scales it
 * to fill the screen, so centering (and everything else) stays correct.
 * This only works because WebSettingsFactory enables the wide viewport
 * in normal mode too (setUseWideViewPort(true)); with it off, the meta
 * tag is ignored and this patch would silently do nothing.
 *
 * Scale steps by device width (CSS px):
 *   < 600px (phones)   -> no scaling (original meta restored)
 *   600-699px          -> 1.2x  (small tablets, portrait)
 *   700-899px          -> 1.3x  (10" tablets, portrait)
 *   >= 900px           -> 1.4x  (tablets, landscape)
 * Recomputed on resize, so rotation and split-screen adapt.
 *
 * The resize handler must derive the device width from the CURRENT
 * innerWidth: once the meta narrows the viewport, innerWidth reports
 * the narrowed width (deviceWidth / z), so deviceWidth is recovered
 * as innerWidth * currentScale. Reading innerWidth raw after scaling
 * would feed the narrowed width back into scaleFor() and oscillate.
 *
 * Desktop Mode is excluded on purpose: it already scales the page
 * (wide viewport + overview mode), and its desktop UA carries the
 * `Antigravity/` token — narrowing the viewport on top would
 * double-scale.
 */
function installTabletScale(global, doc) {
  try {
    var meta = null;
    try {
      meta = doc && doc.querySelector('meta[name="viewport"]');
    } catch (e) {}
    if (!meta || typeof meta.getAttribute !== 'function') return;

    var ua = '';
    try {
      ua = (global.navigator && global.navigator.userAgent) || '';
    } catch (e) {}
    if (ua.indexOf('Antigravity/') !== -1) return;

    var original = '';
    try {
      original = meta.getAttribute('content') || '';
    } catch (e) {}
    if (!original) return;

    function currentScale() {
      try {
        var m = /initial-scale=([\d.]+)/.exec(meta.getAttribute('content') || '');
        var s = m ? parseFloat(m[1]) : 1;
        return s > 0 ? s : 1;
      } catch (e) {
        return 1;
      }
    }

    function deviceWidth() {
      try {
        return (global.innerWidth || 0) * currentScale();
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
      var w = deviceWidth();
      var s = scaleFor(w);
      try {
        if (s <= 1) {
          if (meta.getAttribute('content') !== original) {
            meta.setAttribute('content', original);
          }
          return;
        }
        var content =
          'width=' + Math.round(w / s) +
          ', initial-scale=' + s +
          ', viewport-fit=cover, maximum-scale=' + s;
        if (meta.getAttribute('content') !== content) {
          meta.setAttribute('content', content);
        }
      } catch (e) {}
    }

    apply();
    try {
      global.addEventListener('resize', apply, { passive: true });
    } catch (e) {}
  } catch (e) {}
}
