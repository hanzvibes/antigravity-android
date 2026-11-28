/**
 * patches/touch_model_menu/install.js - arm on-demand when model selector opens.
 */
function install() {
  if (state.installed) return;
  // Fork repair: upstream PR #34 dropped this line, but nothing else
  // ever sets state.hasTouch (state.js defaults it to false), so the
  // `if (!state.hasTouch)` guard below would make install() a
  // permanent no-op. Restore the touch detection.
  state.hasTouch = detectTouch();
  if (!document || !document.addEventListener) return;
  state.installed = true;

  if (!state.hasTouch) {
    return;
  }

  var onInteract = function (ev) {
    var t = ev && ev.target;
    if (!t || !t.closest) return;
    if (t.closest(CONFIG.trigger) || t.closest(CONFIG.panel) || isPanelOpen()) {
      armPanelObserver();
    }
  };

  document.addEventListener('pointerdown', onInteract, { capture: true, passive: true });
  document.addEventListener('click', onInteract, { capture: true, passive: true });

  if (isPanelOpen()) {
    armPanelObserver();
  }
}
