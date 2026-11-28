/**
 * patches/touch_model_menu/scan.js - debounced DOM scan for effort groups.
 */

var SCAN_DEBOUNCE_MS = 80;

function isPanelOpen() {
  try {
    return !!document.querySelector(CONFIG.panel);
  } catch (_) {
    return false;
  }
}

function disconnectObserver() {
  if (state.observer) {
    try { state.observer.disconnect(); } catch (_) {}
  }
}

function enhanceGroup(group) {
  // Fork repair: upstream PR #34's scan() calls enhanceGroup(), but the
  // function exists nowhere in the repo (register.js only defines
  // registerRow). This is the old scan() inline logic, kept verbatim:
  // resolve the menuitem row for the effort group, then register it.
  var row = (group.closest && group.closest(CONFIG.menuItemRole)) || group.parentElement || group;
  registerRow(row);
}

function scan() {
  if (!isPanelOpen()) {
    state.groups = 0;
    disconnectObserver();
    return;
  }
  var groups = [];
  try {
    groups = document.querySelectorAll(CONFIG.effortGroup);
  } catch (_) {
    groups = [];
  }
  state.groups = groups.length;
  for (var i = 0; i < groups.length; i++) {
    enhanceGroup(groups[i]);
  }
}

function scheduleScan() {
  if (state.debounceTimer) clearTimeout(state.debounceTimer);
  state.debounceTimer = setTimeout(function () {
    state.debounceTimer = null;
    scan();
  }, SCAN_DEBOUNCE_MS);
}

function armPanelObserver() {
  var root = document.querySelector(CONFIG.root) || document.body || document.documentElement;
  if (window.MutationObserver && root) {
    if (!state.observer) {
      state.observer = new MutationObserver(scheduleScan);
    }
    try {
      state.observer.observe(root, { childList: true, subtree: true });
    } catch (_) {}
  }
  setTimeout(scan, 16);
  setTimeout(scan, 80);
  setTimeout(scan, 200);
}
