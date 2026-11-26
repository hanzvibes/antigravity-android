#!/usr/bin/env python3
"""
web/patch_main.py - Dynamic patcher for web/main.js.

Applies two independent, idempotent patches to the staged upstream bundle:

1. Desktop Mode toggle injection in the Appearance settings block.
2. Android sandbox disable: the Default and Auto permission presets
   (the ``W1a`` preset mapper in the minified bundle) set
   ``sandboxMode: true``. On Android that makes the core's built-in Linux
   sandbox re-exec ``/proc/self/exe`` -- which resolves to the glibc
   loader (``libloader.so``, see ``RuntimeManager.coreCommand()``) -- with
   Linux namespace/seccomp flags the Android kernel and SELinux reject
   with ``EINVAL``. Every first ``run_command`` with the default presets
   then fails with::

       fork/exec .../libloader.so: invalid argument

   and the agent has to retry with ``BypassSandbox: true``. Android is
   already isolated by the Android Application Sandbox, and the seeded
   agent rules (``modules/core/seed/AGENTS.md``) already forbid desktop
   sandboxing, so the presets are flipped to ``sandboxMode: false`` here.
   Only the flag is changed; the auto-execution policies are left alone.

Safe, idempotent, and resilient to upstream changes. Fail-closed: if a
patch pattern is not found exactly as expected, patching fails so the
build stops instead of shipping a bundle that still breaks run_command.
"""

import sys
import os
import re

# --- Desktop Mode toggle -------------------------------------------------

def _apply_desktop_mode_patch(content):
    """Inject the Desktop Mode toggle; returns new content or None on failure."""
    if "Desktop Mode" in content or "ag_desktop_mode" in content:
        print("[web-patch] Desktop Mode toggle already present in main.js")
        return content

    # 1. State hook injection pattern in Appearance component:
    # Matches: var C=g!==3,D=g!==2,E=F=>G=>{F===t&&v(G)}; or legacy var B=f!==3,C=f!==2,D=E=>G=>{E===r&&u(G)};
    hook_pattern = re.compile(r'(var\s+[A-Za-z0-9_$]+=[A-Za-z0-9_$]+!==3,\s*[A-Za-z0-9_$]+=[A-Za-z0-9_$]+!==2,\s*[A-Za-z0-9_$]+=[A-Za-z0-9_$]+=>\s*[A-Za-z0-9_$]+=>\{.*?\};)')
    hook_match = hook_pattern.search(content)

    # 2. JSX Theme element injection: find Theme element in Appearance
    theme_idx = content.find('{label:"Theme"')
    theme_match = None
    react_id = "A"
    if theme_idx != -1:
        # Search backwards within a reasonable window (e.g. 100 chars) for createElement
        window_start = max(0, theme_idx - 100)
        window_end = min(len(content), theme_idx + 500)
        window_text = content[window_start:window_end]
        theme_pattern = re.compile(
            r'([A-Za-z0-9_$]+)\.createElement\(([A-Za-z0-9_$]+),\{label:"Theme",.*?onSelect:[A-Za-z0-9_$]+\}\)'
        )
        theme_match = theme_pattern.search(window_text)
        if theme_match:
            react_id = theme_match.group(1)

    if not hook_match or not theme_match:
        print(f"[web-patch] patterns not matched: hook={bool(hook_match)}, theme={bool(theme_match)}", file=sys.stderr)
        return None

    orig_hook = hook_match.group(1)
    injected_hook = (
        f"var [isDesktop,setIsDesktop]=(0,{react_id}.useState)(()=>{{"
        "try{if(window.Android&&typeof window.Android.isDesktopMode==='function')return window.Android.isDesktopMode();"
        "var s=localStorage.getItem('ag_desktop_mode');return s===null?!1:s==='true'}catch(_){return !1}});"
        f"var onDesktopToggle=(0,{react_id}.useCallback)(v=>{{"
        "setIsDesktop(v);try{localStorage.setItem('ag_desktop_mode',String(v));"
        "if(window.Android&&typeof window.Android.setDesktopMode==='function')window.Android.setDesktopMode(v)}catch(_){}},[]);"
        + orig_hook
    )

    # Detect switch and setting item components
    # Look for setting item component used with rightElement or contrast setting
    item_comp = "v3"
    switch_comp = "dX"
    re_idx = content.find('rightElement:')
    if re_idx != -1:
        re_window = content[max(0, re_idx - 150):min(len(content), re_idx + 150)]
        item_m = re.search(r'([A-Za-z0-9_$]+)\.createElement\(([A-Za-z0-9_$]+),\{label:[^,]+,description:[^,]+,rightElement:', re_window)
        if item_m:
            item_comp = item_m.group(2)
        sw_m = re.search(r'rightElement:[A-Za-z0-9_$]+\.createElement\(([A-Za-z0-9_$]+),\{checked:', re_window)
        if sw_m:
            switch_comp = sw_m.group(1)

    orig_theme = theme_match.group(0)
    injected_theme = (
        orig_theme
        + f',{react_id}.createElement({item_comp},{{label:"Desktop Mode",description:"Use desktop viewport and user agent for the workspace",'
        + f'rightElement:{react_id}.createElement({switch_comp},{{checked:isDesktop,onCheckedChange:onDesktopToggle}})}})'
    )

    content = content.replace(orig_hook, injected_hook, 1)
    content = content.replace(orig_theme, injected_theme, 1)

    print("[web-patch] Successfully patched Desktop Mode toggle into main.js (mobile by default, English)")
    return content


# --- Android sandbox disable (run_command libloader.so EINVAL) -----------

# The W1a preset mapper is the only place in the bundle that enables
# desktop sandboxing: every other sandboxMode in the file is already
# false/undefined. Anchors are kept short on purpose -- the minified
# function name (W1a) changes between upstream versions, but the preset
# names ("auto" / default) and the sandboxMode flag do not.
_SANDBOX_AUTO_ON = 'case "auto":return{sandboxMode:!0'
_SANDBOX_AUTO_OFF = 'case "auto":return{sandboxMode:!1'
_SANDBOX_DEFAULT_ON = 'default:return{sandboxMode:!0'
_SANDBOX_DEFAULT_OFF = 'default:return{sandboxMode:!1'


def _apply_sandbox_patch(content):
    """Flip Default/Auto presets to sandboxMode:false; new content or None."""
    for on, off, name in (
        (_SANDBOX_AUTO_ON, _SANDBOX_AUTO_OFF, '"auto" preset'),
        (_SANDBOX_DEFAULT_ON, _SANDBOX_DEFAULT_OFF, 'default preset'),
    ):
        on_count = content.count(on)
        off_count = content.count(off)
        if on_count == 1 and off_count == 0:
            content = content.replace(on, off, 1)
            print(f"[web-patch] sandboxMode disabled for {name} (Android has no desktop sandboxing)")
        elif on_count == 0 and off_count >= 1:
            print(f"[web-patch] sandboxMode already disabled for {name}")
        else:
            print(
                f"[web-patch] sandbox pattern ambiguous for {name}: "
                f"on={on_count}, off={off_count} (expected exactly one of them)",
                file=sys.stderr,
            )
            return None
    return content


def patch_main(file_path):
    if not os.path.isfile(file_path):
        print(f"[web-patch] file not found: {file_path}", file=sys.stderr)
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # The two patches are independent: a bundle that already carries the
    # Desktop Mode toggle must still get the sandbox fix (an earlier
    # version returned early here and skipped it).
    content = _apply_desktop_mode_patch(content)
    if content is None:
        return False
    content = _apply_sandbox_patch(content)
    if content is None:
        return False

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("[web-patch] main.js patched (Desktop Mode toggle + sandboxMode off for Default/Auto)")
    return True

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "main.js")
    if not patch_main(path):
        sys.exit(1)
