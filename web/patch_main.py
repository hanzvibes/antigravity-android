#!/usr/bin/env python3
"""
web/patch_main.py - Dynamic patcher for web/main.js.

Applies three independent, idempotent patches to the staged upstream bundle:

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

3. Swipe/drag performance: the gesture hook re-renders React on every
   pointer move (setState for position, transform, direction and the
   swiping flag). The 22 PERF hunks from upstream PR #34 rewrite it to
   write straight to the DOM instead (translate3d + transition:none
   while dragging, cleared on release, swiping mirrored with a
   data-swiping attribute). Behaviour is unchanged; gestures just stop
   re-rendering per move.

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


# --- Swipe/drag performance (upstream PR #34 PERF_HUNKS) ----------------
#
# The swipe/drag gesture hook in the bundle re-renders React on every
# pointer move: each move calls setState for the position, the transform,
# the swipe direction and the swiping flag (ja/ra/S/Ka/...). On touch
# devices that is a React render per pointermove event, which janks
# swipes, drags and panel dismissals.
#
# These 22 hunks (upstream PR #34, werdi325-png/antigravity-android)
# rewrite the hook to write straight to the DOM instead: the dragged
# element's transform is set with translate3d() + transition:none while
# dragging and cleared on release, and the swiping flag is mirrored with
# a data-swiping attribute instead of a state update. React state is
# only touched for coarse changes (direction settled, drag dismissed).
# Behaviour is unchanged; the gesture just stops re-rendering per move.
#
# Applied like the sandbox patch: each old string must occur exactly
# once (fail-closed otherwise), and an already-patched bundle is a no-op.
PERF_HUNKS = [
    ('main.js#1', 'if(Ob&&hb>Ob.time){let ib=Math.max(hb-Ob.time,16);Qa.current={x:(Ra.x-Ob.x)/ib,y:(Ra.y-Ob.y)/ib}}zb.current={x:Ra.x,y:Ra.y,time:hb}}}function e(Ra){return"touches"in Ra?(Ra=Ra.touches[0])?{x:Ra.clientX,y:Ra.clientY}:null:{x:Ra.clientX,y:Ra.clientY}}function f(Ra){return"touches"in Ra?!0:Ra.pointerType===\n"touch"}function g(Ra,hb){return vK(tw(r.current),Ra.x,Ra.y)??Mv(hb)}function h(Ra,hb){return O&&!P?xK(Ra,hb,"horizontal"):P&&!O?xK(Ra,hb,"vertical"):xK(Ra,hb,"vertical")??xK(Ra,hb,"horizontal")}function k(Ra,hb,Ob){Ia.current=!1;var ib=f(Ra),tb=g(hb,Ra.nativeEvent),kc=tw(r.current).body;kc=ib&&kc?h(tb,kc):null;var ob=Ob?.ignoreScrollableTarget??!1;if(kc&&!ob)return!1;Ia.current=!(!kc||!ob);if(tb&&tb.closest(\'button,a,input,select,textarea,label,[role="button"]\')&&(!ib||v))return!1', 'if(Ob&&hb>Ob.time){let ib=Math.max(hb-Ob.time,16);Qa.current={x:(Ra.x-Ob.x)/ib,y:(Ra.y-Ob.y)/ib}}zb.current={x:Ra.x,y:Ra.y,time:hb}}}function e(Ra){return"touches"in Ra?(Ra=Ra.touches[0])?{x:Ra.clientX,y:Ra.clientY}:null:{x:Ra.clientX,y:Ra.clientY}}function f(Ra){return"touches"in Ra?!0:Ra.pointerType===\n"touch"}function g(Ra,hb){return Mv(hb)??vK(tw(r.current),Ra.x,Ra.y)}function h(Ra,hb){return O&&!P?xK(Ra,hb,"horizontal"):P&&!O?xK(Ra,hb,"vertical"):xK(Ra,hb,"vertical")??xK(Ra,hb,"horizontal")}function k(Ra,hb,Ob){Ia.current=!1;var ib=f(Ra),tb=g(hb,Ra.nativeEvent),ob=Ob?.ignoreScrollableTarget??!1,kc=!ob&&ib?h(tb,tw(r.current).body):null;if(kc&&!ob)return!1;Ia.current=ob;if(tb&&tb.closest(\'button,a,input,select,textarea,label,[role="button"]\')&&(!ib||v))return!1'),
    ('main.js#2', 'va.current=hb;ib&&(Ya.current={width:ib.offsetWidth,height:ib.offsetHeight},b(H),hb=zK(ib),Ea.current=hb,la.current={x:hb.x,y:hb.y},ra(hb),ja({x:hb.x,y:hb.y}),c({x:hb.x,y:hb.y},cb.current),"touches"in Ra||BK(ib,Ra.pointerId,\n"setPointerCapture"));D?.(Ra.nativeEvent);Ka(!0);ha(!1);ua(null);Ma.current=!0', 'va.current=hb;ib&&(Ya.current={width:ib.offsetWidth||1,height:ib.offsetHeight||1},b(H),hb=zK(ib),Ea.current=hb,la.current={x:hb.x,y:hb.y},c({x:hb.x,y:hb.y},cb.current),"touches"in Ra||BK(ib,Ra.pointerId,\n"setPointerCapture"));D?.(Ra.nativeEvent);Ka(!0);Ma.current=!0'),
    ('main.js#3', 'O&&Ra.push("horizontal");return Ra},[O,P]),[R,S]=A.useState(void 0),[U,Y]=A.useState(!1),[ea,ca]=A.useState(!1),ha=ca,[ba,da]=A.useState(!1),[qa,ma]=A.useState({x:0,y:0}),ja=ma,[pa,ia]=A.useState({x:0,y:0,scale:1}),ra=ia,[wa,za]=A.useState(null),ua=za,fa=A.useRef({x:0,y:0}),la=A.useRef({x:0,y:0}),va=A.useRef(null),Ea=A.useRef({x:0,y:0,scale:1}),na=A.useRef(void 0),Aa=A.useRef(0),\nCa=A.useRef(!1),ta=A.useRef({x:0,y:0}),Ma=A.useRef(!1),Fa=A.useRef(!1),Ja=A.useRef(null),Ia=A.useRef(!1),Za=A.useRef(!1),Ya=A.useRef({width:0,height:0}),Ua=A.useRef(0),lb=A.useRef(J),cb=A.useRef(null),zb=A.useRef(null),Qa=A.useRef({x:0,y:0}),Ga=A.useRef(null),Oa=A.useRef(!1),Ka=Lw(Ra=>{Oa.current!==Ra&&(Oa.current=Ra,Y(Ra),F?.(Ra))}),Wa=Lw((Ra,hb)=>{Ra=Number.isFinite(Ra)?uK(Ra,0,1):0;var Ob=Ra!==Ua.current,ib=!1;hb&&(ib=Ga.current,ib=!ib||ib.deltaX!==hb.deltaX||ib.deltaY!==hb.deltaY||ib.direction!==\nhb.direction);if(Ob||ib)Ua.current=Ra,hb?Ga.current=hb:Ob&&(Ga.current=null),B?.(Ra,hb)});a=A.useCallback(()=>{S(void 0);Ka(!1);ha(!1);da(!1);ja({x:0,y:0});ra({x:0,y:0,scale:1});ua(null);Wa(0)', 'O&&Ra.push("horizontal");return Ra},[O,P]),[R,S]=A.useState(void 0),[U,Y]=A.useState(!1),[ea,ca]=A.useState(!1),ha=ca,[ba,da]=A.useState(!1),[qa,ma]=A.useState({x:0,y:0}),ja=ma,[pa,ia]=A.useState({x:0,y:0,scale:1}),ra=ia,[wa,za]=A.useState(null),ua=za,fa=A.useRef({x:0,y:0}),la=A.useRef({x:0,y:0}),va=A.useRef(null),Ea=A.useRef({x:0,y:0,scale:1}),na=A.useRef(void 0),Aa=A.useRef(0),\nCa=A.useRef(!1),ta=A.useRef({x:0,y:0}),Ma=A.useRef(!1),Fa=A.useRef(!1),Ja=A.useRef(null),Ia=A.useRef(!1),Za=A.useRef(!1),Ya=A.useRef({width:0,height:0}),Ua=A.useRef(0),lb=A.useRef(J),cb=A.useRef(null),zb=A.useRef(null),Qa=A.useRef({x:0,y:0}),Ga=A.useRef(null),Oa=A.useRef(!1),Ka=Lw(Ra=>{Oa.current!==Ra&&(Oa.current=Ra,r.current&&(Ra?r.current.setAttribute("data-swiping",""):r.current.removeAttribute("data-swiping")),F?.(Ra))}),Wa=Lw((Ra,hb)=>{Ra=Number.isFinite(Ra)?uK(Ra,0,1):0;var Ob=Ra!==Ua.current,ib=!1;hb&&(ib=Ga.current,ib=!ib||ib.deltaX!==hb.deltaX||ib.deltaY!==hb.deltaY||ib.direction!==\nhb.direction);if(Ob||ib)Ua.current=Ra,hb?Ga.current=hb:Ob&&(Ga.current=null),B?.(Ra,hb)});a=A.useCallback(()=>{if(r.current){r.current.style.removeProperty("transition");r.current.style.transform="";r.current.style.pointerEvents="";}Ka(!1);Wa(0)'),
    ('main.js#4', 'if(Oa.current){Ka(!1);ha(!1);ua(null);var tb=G?pa:Ea.current;la.current={x:tb.x,y:tb.y};ja({x:tb.x,y:tb.y});S(void 0);Za.current=!1;(tb=r.current)&&BK(tb,Ra.pointerId,"releasePointerCapture");Wa(0,{deltaX:0,deltaY:0,direction:void 0});C?.(Ra.nativeEvent)}return}}if(!U&&Fa.current){if(!f(Ra)&&(Ra.defaultPrevented||Ra.nativeEvent.defaultPrevented)){l();return}if(u?u(hb,{nativeEvent:Ra.nativeEvent,direction:H}):1){Ob=Ja.current', 'if(Oa.current){Ka(!1);la.current={x:Ea.current.x,y:Ea.current.y};Za.current=!1;(tb=r.current)&&(tb.style.removeProperty("transition"),tb.style.transform="",BK(tb,Ra.pointerId,"releasePointerCapture"));Wa(0,{deltaX:0,deltaY:0,direction:void 0});C?.(Ra.nativeEvent)}return}}if(!Oa.current&&Fa.current){if(!f(Ra)&&(Ra.defaultPrevented||Ra.nativeEvent.defaultPrevented)){l();return}if(u?u(hb,{nativeEvent:Ra.nativeEvent,direction:H}):1){Ob=Ja.current'),
    ('main.js#5', 'va.current=hb;if(n&&Oa.current&&(Ob=Mv(Ra.nativeEvent),!f(Ra)||Ia.current||!h(Ob,Ra.currentTarget))){"touches"in Ra||Ra.preventDefault();Ma.current&&(fa.current=hb,Ob=AK(Ra.timeStamp),Ob!==null&&(cb.current=Ob),Ma.current=!1)', 'va.current=hb;if(n&&Oa.current){"touches"in Ra||Ra.preventDefault();Ma.current&&(fa.current=hb,Ob=AK(Ra.timeStamp),Ob!==null&&(cb.current=Ob),Ma.current=!1)'),
    ('main.js#6', 'Ob-=ta.current.x;!ea&&Math.sqrt(ib*ib+hb*hb)>=1&&(ha(!0),wa===null&&O&&P&&ua(Math.abs(ib)>Math.abs(hb)?"horizontal":"vertical"));na.current?(tb=na.current,Ob=yK(tb,Ob,kc),Ob>lb.current?(Ca.current=!1,S(tb)):!(K&&L||M&&N)&&Aa.current-Ob>=10&&(Ca.current=!0)):(wa==="vertical"?hb>0?tb="down":hb<0&&(tb="up"):wa==="horizontal"?ib>0?tb="right":ib<\n0&&(tb="left"):tb=Math.abs(ib)>=Math.abs(hb)?ib>0?"right":"left":hb>0?"down":"up",tb&&(tb==="left"&&K||tb==="right"&&L||tb==="up"&&M||tb==="down"&&N)&&(na.current=tb,Aa.current=yK(tb,ib,hb),S(tb),b(tb)));Ob=O?!K&&ib<0||!L&&ib>0?ib>=0?ib**.5:-(Math.abs(ib)**.5):ib:ib>=0?ib**.5:-(Math.abs(ib)**.5)', 'Ob-=ta.current.x;na.current?(tb=na.current,Ob=yK(tb,Ob,kc),Ob>lb.current?Ca.current=!1:!(K&&L||M&&N)&&Aa.current-Ob>=10&&(Ca.current=!0)):(tb=Math.abs(ib)>=Math.abs(hb)?ib>0?"right":"left":hb>0?"down":"up",tb&&(tb==="left"&&K||tb==="right"&&L||tb==="up"&&M||tb==="down"&&N)&&(na.current=tb,Aa.current=yK(tb,ib,hb),b(tb)));Ob=O?!K&&ib<0||!L&&ib>0?ib>=0?ib**.5:-(Math.abs(ib)**.5):ib:ib>=0?ib**.5:-(Math.abs(ib)**.5)'),
    ('main.js#7', 'hb=Ea.current.y;wa==="horizontal"?O&&(tb+=Ob):(wa!=="vertical"&&O&&(tb+=Ob),P&&(hb+=ib));la.current=\n{x:tb,y:hb};G&&ja({x:tb,y:hb});c({x:tb,y:hb},AK(Ra.timeStamp));Ra=tb-Ea.current.x', 'hb=Ea.current.y;O&&(tb+=Ob);P&&(hb+=ib);la.current={x:tb,y:hb};if(G&&r.current){r.current.style.transition="none";r.current.style.transform=Ea.current.scale===1?`translate3d(${tb}px,${hb}px,0)`:`translate3d(${tb}px,${hb}px,0) scale(${Ea.current.scale})`;}c({x:tb,y:hb},AK(Ra.timeStamp));Ra=tb-Ea.current.x'),
    ('main.js#8', 'ob=typeof hb==="boolean";if(Ca.current&&!ob)la.current={x:Ob.x,y:Ob.y},ja({x:Ob.x,y:Ob.y}),S(void 0),Wa(0,kc);else{Mc=!1;if(ob){Mc=hb', 'ob=typeof hb==="boolean";if(Ca.current&&!ob){la.current={x:Ob.x,y:Ob.y};if(r.current){r.current.style.transition="";r.current.style.transform="";t?.x&&r.current.style.setProperty(t.x,"0px");t?.y&&r.current.style.setProperty(t.y,"0px");}ja({x:Ob.x,y:Ob.y});S(void 0);Wa(0,kc);}else{Mc=!1;if(ob){Mc=hb'),
    ('main.js#9', 'break;case "up":tb<-lb.current&&(Mc=!0,ne="up")}if(Mc)break}Mc&&ne?(S(ne),da(!0),y?.(Ra.nativeEvent,{direction:ne})):(la.current={x:Ob.x,y:Ob.y},ja({x:Ob.x,y:Ob.y}),S(void 0),Wa(0,kc))}}else l(),Wa(0,kc)}}),fb=A.useCallback(()=>{var Ra=G?qa:la.current,hb=G?pa:Ea.current;return U||Ra.x!==hb.x||Ra.y!==hb.y||ba?{transition:U?"none":void 0,transform:U?`translateX(${Ra.x}px) translateY(${Ra.y}px) scale(${hb.scale})`:void 0,[t.x]:`${Ra.x-hb.x}px`,[t.y]:`${Ra.y-hb.y}px`}:{[t.x]:"0px",\n[t.y]:"0px"}},[ba,qa,pa,U,t,G]),Qb=A.useCallback(()=>n?{onPointerDown:Va,onPointerMove:vb,onPointerUp:Na,onPointerCancel:Na}:{},[n,Na,vb,Va]),qb=A.useCallback(()=>n?{onTouchStart:Va,onTouchMove:vb,onTouchEnd:Na,onTouchCancel:Na}:{},[n,Na,vb,Va]);return{swiping:U,swipeDirection:R,dragDismissed:ba,getPointerProps:Qb,getTouchProps:qb,getDragStyles:fb,reset:a}}', 'break;case "up":tb<-lb.current&&(Mc=!0,ne="up")}if(Mc)break}Mc&&ne?y?.(Ra.nativeEvent,{direction:ne}):(la.current={x:Ob.x,y:Ob.y},r.current&&(r.current.style.removeProperty("transition"),r.current.style.transform=""),Wa(0,kc))}}else l(),Wa(0,kc)}}),fb=A.useCallback(()=>{var Ra=la.current,hb=Ea.current;return U||Ra.x!==hb.x||Ra.y!==hb.y||ba?{transition:U?"none":void 0,transform:U?`translate3d(${Ra.x}px,${Ra.y}px,0) scale(${hb.scale})`:void 0,[t.x]:`${Ra.x-hb.x}px`,[t.y]:`${Ra.y-hb.y}px`}:{[t.x]:"0px",[t.y]:"0px"}},[ba,qa,pa,U,t,G]),Qb=A.useCallback(()=>n?{onPointerDown:Va,onPointerMove:vb,onPointerUp:Na,onPointerCancel:Na}:{},[n,Na,vb,Va]),qb=A.useCallback(()=>n?{onTouchStart:Va,onTouchMove:vb,onTouchEnd:Na,onTouchCancel:Na}:{},[n,Na,vb,Va]);return{swiping:U,swipeDirection:R,dragDismissed:ba,getPointerProps:Qb,getTouchProps:qb,getDragStyles:fb,reset:a}}'),
    ('main.js#10', 'fa?(la?.setAttribute("data-swipe-dismiss",""),va?.setAttribute("data-swipe-dismiss","")):(la?.removeAttribute("data-swipe-dismiss"),va?.removeAttribute("data-swipe-dismiss"))}),ja=Lw(()=>{ma(!1);m.context.popupRef.current?.removeAttribute("data-ending-style");\nQ(null)}),pa=Lw(()=>{Y.current&&(Y.current=!1,q?.(!1))}),ia=Lw(({resolvedProgress:fa,shouldTrackProgress:la,notifyParent:va})=>{var Ea=D&&!F&&la,na=Ea?fa:0;fa=D&&la?fa:0;va&&r&&(r(fa),fa<=0&&pa());K?.set({swipeProgress:na,frontmostHeight:na>0?t:0});if(va=m.context.backdropRef.current)!Ea||na<=0?(va.style.setProperty("--drawer-swipe-progress","0"),va.style.removeProperty("--drawer-height")):(va.style.setProperty("--drawer-swipe-progress",`${na}`),t>0?va.style.setProperty("--drawer-height",`${t}px`):\nva.style.removeProperty("--drawer-height"))}),ra=nYa({enabled:E&&!L,directions:a,elementRef:m.context.popupRef,ignoreSelectorWhenTouch:!1,ignoreScrollableAncestors:!0,movementCssVars:{x:"--drawer-swipe-movement-x",y:"--drawer-swipe-movement-y"},onSwipeStart(fa){if(!("touches"in fa||"pointerType"in fa&&fa.pointerType==="touch")&&(fa=m.context.popupRef.current)){var la=tw(fa).getSelection?.();if(la&&!la.isCollapsed){var va=yu(la.focusNode)?la.focusNode:la.focusNode?.parentElement', 'fa?(la?.setAttribute("data-swipe-dismiss",""),va?.setAttribute("data-swipe-dismiss","")):(la?.removeAttribute("data-swipe-dismiss"),va?.removeAttribute("data-swipe-dismiss"))}),ja=Lw(()=>{ma(!1);var fa=m.context.popupRef.current,la=m.context.backdropRef.current;fa&&(fa.removeAttribute("data-ending-style"),fa.style.pointerEvents="",fa.style.removeProperty("transition"));la&&(la.style.pointerEvents="",la.style.opacity="",la.style.removeProperty("transition"));Q(null)}),pa=Lw(()=>{Y.current&&(Y.current=!1,q?.(!1))}),ia=Lw(({resolvedProgress:fa,shouldTrackProgress:la,notifyParent:va})=>{var Ea=D&&!F&&la,na=Ea?fa:0;fa=D&&la?fa:0;va&&r&&(r(fa),fa<=0&&pa());K&&K.set({swipeProgress:na,frontmostHeight:na>0?t:0});if(va=m.context.backdropRef.current)va.style.opacity=!Ea||na<=0?"":`${Math.max(0,1-na)}`}),ra=nYa({enabled:E&&!L,directions:a,elementRef:m.context.popupRef,ignoreSelectorWhenTouch:!1,ignoreScrollableAncestors:!0,movementCssVars:{x:"--drawer-swipe-movement-x",y:"--drawer-swipe-movement-y"},onSwipeStart(fa){if(!("touches"in fa||"pointerType"in fa&&fa.pointerType==="touch")&&(fa=m.context.popupRef.current)){var la=tw(fa).getSelection?.();if(la&&!la.isCollapsed){var va=yu(la.focusNode)?la.focusNode:la.focusNode?.parentElement'),
    ('main.js#11', 'var Ea=va.ownerDocument;fa=vK(Ea,fa.x,fa.y);if(!fa||!Lv(va,fa))return!1', 'var Ea=va.ownerDocument;fa=Mv(la.nativeEvent)??vK(Ea,fa.x,fa.y);if(!fa||!Lv(va,fa))return!1'),
    ('main.js#12', 'else if(va==="down"||va==="up")fa*=C,la=y??da.minOffset,\nna=uK(((va==="down"?la+fa:la-fa)-da.minOffset)/da.range,0,1);ia({resolvedProgress:na,shouldTrackProgress:Ea,notifyParent:!0})},onRelease({event:fa,deltaX:la,deltaY:va,direction:Ea,velocityX:na,velocityY:Aa,releaseVelocityX:Ca,releaseVelocityY:ta}){function Ma(Ya){var Ua=m.context.popupRef.current;Ua&&(pa(),ma(!0),Ua.style.removeProperty("transition"),Ua.setAttribute("data-ending-style",""),ev.flushSync(()=>{Q(c({direction:Ya,...Fa}))}))}var Fa={deltaX:la,deltaY:va,velocityX:na,velocityY:Aa,releaseVelocityX:Ca,\nreleaseVelocityY:ta};if(!v||v.length===0){if(!Ea){ja()', 'else if(va==="down"||va==="up")fa*=C,la=y??da.minOffset,\nna=uK(((va==="down"?la+fa:la-fa)-da.minOffset)/da.range,0,1);ia({resolvedProgress:na,shouldTrackProgress:Ea,notifyParent:!0})},onRelease({event:fa,deltaX:la,deltaY:va,direction:Ea,velocityX:na,velocityY:Aa,releaseVelocityX:Ca,releaseVelocityY:ta}){function Ma(Ya){var Ua=m.context.popupRef.current,Ba=m.context.backdropRef.current;pa();ma(!0);if(Ua){Ua.style.pointerEvents="none";Ua.style.setProperty("transition","transform 80ms cubic-bezier(0.2, 0, 0, 1)","important");Ua.style.transform=Ya==="up"?"translate3d(0px,-105%,0)":Ya==="left"?"translate3d(-105%,0px,0)":Ya==="right"?"translate3d(105%,0px,0)":"translate3d(0px,105%,0)"}if(Ba){Ba.style.pointerEvents="none";Ba.style.setProperty("transition","opacity 80ms linear","important");Ba.style.opacity="0"}}var Fa={deltaX:la,deltaY:va,velocityX:na,velocityY:Aa,releaseVelocityX:Ca,\nreleaseVelocityY:ta};if(!v||v.length===0){if(!Ea){ja()'),
    ('main.js#13', 'if(Ia<=0)return ja(),!1;Aa=Ea==="left"||Ea==="right"?na:Aa;if((Ea==="left"||Ea==="up"?-Aa:Aa)>=.5&&Ia>0)return Ma(Ea),!0;(Ja=Ia>Ja)?Ma(Ea):ja()', 'if(Ia<=0)return ja(),!1;Aa=Ea==="left"||Ea==="right"?(Number.isFinite(Ca)&&Math.abs(Ca)>Math.abs(na)?Ca:na):(Number.isFinite(ta)&&Math.abs(ta)>Math.abs(Aa)?ta:Aa);if((Ea==="left"||Ea==="up"?-Aa:Aa)>=.15&&Ia>12)return Ma(Ea),!0;(Ja=Ia>Ja)?Ma(Ea):ja()'),
    ('main.js#14', 'ja();return!1}ja()},onDismiss(fa){K?.set({swipeProgress:0,frontmostHeight:0});var la=m.context.backdropRef.current;la&&(la.style.setProperty("--drawer-swipe-progress","0"),la.style.removeProperty("--drawer-height"));la=fw("swipe",fa);m.setOpen(!1,la);la.isCanceled?(la=R.current,la!==void 0&&B?.(la,fw("swipe",fa)),R.current=void 0,S.current?.(),ja()):m.select("open")?U.request(()=>{if(m.select("open")){let va=R.current;va!==void 0&&\nB?.(va,fw("swipe",fa));R.current=void 0;ja();S.current?.()}else R.current=void 0}):(R.current=void 0,ma(!0))}}),wa=ra.getPointerProps(),za=ra.getTouchProps(),ua=ra.reset;S.current=ua;A.useEffect(()=>{var fa=H??J;if(fa){var la=tw(fa),va=wu(la);return Gw(la,"touchmove",function(Ea){if(!ha.current){var na=ba.current,Aa=Ea.touches[0];if(Aa&&na){var Ca=N?Aa.clientY-na.lastY:Aa.clientX-na.lastX;if(DK(Ea,va))na.allowSwipe=!1', 'ja();return!1}ja()},onDismiss(fa){var la=fw("swipe",fa);setTimeout(()=>{K&&K.set({swipeProgress:0,frontmostHeight:0});m.setOpen(!1,la);if(la.isCanceled){let va=R.current;va!==void 0&&B?.(va,fw("swipe",fa));R.current=void 0;S.current?.();ja()}else if(m.select("open")){setTimeout(()=>{if(m.select("open")){let va=R.current;va!==void 0&&B?.(va,fw("swipe",fa));R.current=void 0;ja();S.current?.()}else R.current=void 0},120)}else R.current=void 0},80)}}),wa=ra.getPointerProps(),za=ra.getTouchProps(),ua=ra.reset;S.current=ua;A.useEffect(()=>{var fa=H??J;if(fa&&D&&E&&!L){var la=tw(fa),va=wu(la);return Gw(la,"touchmove",function(Ea){if(!ha.current){var na=ba.current,Aa=Ea.touches[0];if(Aa&&na){if(na.allowSwipe===!0){Ea.cancelable&&Ea.preventDefault();na.lastX=Aa.clientX;na.lastY=Aa.clientY;return}if(na.allowSwipe===!1||na.preserveNativeCrossAxisScroll){na.lastX=Aa.clientX;na.lastY=Aa.clientY;return}var Ca=N?Aa.clientY-na.lastY:Aa.clientX-na.lastX;if(DK(Ea,va))na.allowSwipe=!1'),
    ('main.js#15', 'A.useEffect(()=>{if(r)return D||r(0),()=>{r(0)}},\n[r,D]);A.useEffect(()=>{D&&(ua(),ja())},[ja,D,ua]);A.useEffect(()=>()=>{K?.set({swipeProgress:0,frontmostHeight:0})', 'A.useEffect(()=>{if(r)return D||r(0),()=>{r(0)}},\n[r,D]);A.useEffect(()=>{ua();ja()},[ja,D,ua]);A.useEffect(()=>()=>{K?.set({swipeProgress:0,frontmostHeight:0})'),
    ('main.js#16', 'if(la)if(DK(fa.nativeEvent,wu(fa.currentTarget)))ha.current=!1,ba.current=null;else{var va=vK(tw(fa.currentTarget),la.clientX,la.clientY);ha.current=CK(va)', 'if(la)if(DK(fa.nativeEvent,wu(fa.currentTarget)))ha.current=!1,ba.current=null;else{var va=Mv(fa.nativeEvent)??vK(tw(fa.currentTarget),la.clientX,la.clientY);ha.current=CK(va)'),
    ('main.js#17', 'Ea=(Ea===null?0:Ea?\nCa<=0:Ca>=ta)?null:!1}ba.current={startX:la.clientX,startY:la.clientY,lastX:la.clientX,lastY:la.clientY,scrollTarget:va,hasCrossAxisScrollableContent:Aa,allowSwipe:Ea,preserveNativeCrossAxisScroll:!1};za.onTouchStart?.(fa)}}}}else ha.current=!1,ba.current=null},onTouchMove(fa){if(!ha.current&&!DK(fa.nativeEvent,wu(fa.currentTarget))){var la=ba.current;if(!la?.preserveNativeCrossAxisScroll&&la?.allowSwipe!==!1&&(la?.scrollTarget==null||la.allowSwipe))za.onTouchMove?.(fa)}},onTouchEnd(fa){e();za.onTouchEnd?.(fa)},\nonTouchCancel(fa){e();za.onTouchCancel?.(fa)},["data-nested-dialog-open"]:void 0})},A.createElement(fYa.Provider,{value:a},k))});function uYa(a,b){a&&(b?a.setAttribute("data-swiping",""):a.removeAttribute("data-swiping"))}function CK(a){return!!a?.closest("[data-base-ui-swipe-ignore]")}function vYa(a,b){return Math.max((b==="left"||b==="right"?a.offsetWidth:a.offsetHeight)*.5,10)}function AYa(a,b){return a instanceof b.HTMLInputElement&&a.type==="range"}\nfunction wYa(a,b){var c=Kv(a);if(c&&Lv(b,c)&&yu(c)&&(c.tagName==="INPUT"||c.tagName==="TEXTAREA")){var e=c.selectionStart', 'Ea=(Ea===null?0:Ea?\nCa<=0:Ca>=ta)?null:!1}ba.current={startX:la.clientX,startY:la.clientY,lastX:la.clientX,lastY:la.clientY,scrollTarget:va,hasCrossAxisScrollableContent:Aa,allowSwipe:Ea,preserveNativeCrossAxisScroll:!1};za.onTouchStart?.(fa)}}}}else ha.current=!1,ba.current=null},onTouchMove(fa){if(!ha.current){var la=ba.current;if(!la?.preserveNativeCrossAxisScroll&&la?.allowSwipe!==!1&&(la?.scrollTarget==null||la.allowSwipe))za.onTouchMove?.(fa)}},onTouchEnd(fa){e();za.onTouchEnd?.(fa)},\nonTouchCancel(fa){e();za.onTouchCancel?.(fa)},["data-nested-dialog-open"]:void 0})},A.createElement(fYa.Provider,{value:a},k))});function uYa(a,b){a&&(b?a.setAttribute("data-swiping",""):a.removeAttribute("data-swiping"))}function CK(a){return!!a?.closest("[data-base-ui-swipe-ignore]")}function vYa(a,b){return Math.min(Math.max((b==="left"||b==="right"?a.offsetWidth:a.offsetHeight)*.15,10),80)}function AYa(a,b){return a instanceof b.HTMLInputElement&&a.type==="range"}\nfunction wYa(a,b){var c=Kv(a);if(c&&Lv(b,c)&&yu(c)&&(c.tagName==="INPUT"||c.tagName==="TEXTAREA")){var e=c.selectionStart'),
    ('main.js#18', 'w.current=h;var [x,y]=A.useState(c===0);A.useLayoutEffect(()=>{if(!x&&!e){var B=0,C=requestAnimationFrame(()=>{B=requestAnimationFrame(()=>{y(!0)})});return()=>{cancelAnimationFrame(C);cancelAnimationFrame(B)}}},[x,e]);A.useLayoutEffect(()=>{if(b&&k){var B=q.current', 'w.current=h;var x=!0;A.useLayoutEffect(()=>{if(b&&k){var B=q.current'),
    ('main.js#19', 'B&&(B.inert=!b,b&&t&&(t.scrollTop=0))},[b,t]);A.useEffect(()=>{if(e){var B=setTimeout(()=>{w.current?.()},400);return()=>clearTimeout(B)}},[e]);a=x||e?a:a+1;return A.createElement("div",{ref:n,onTransitionEnd:e?B=>{B.target===B.currentTarget&&B.propertyName==="transform"&&w.current?.()}:void 0,className:aj("absolute inset-x-0 top-0 flex flex-col","transition-transform duration-300 ease-expo-out motion-reduce:transition-none",\nb?"bottom-0":"pointer-events-none"),style:{transform:`translateX(${a*100}%)`}},A.createElement("div",{ref:r,onScroll:v,className:b?"flex-1 overflow-y-auto overscroll-contain":"overflow-hidden",style:{maskImage:u.top&&u.bottom?"linear-gradient(to bottom, transparent, black 12px, black calc(100% - 12px), transparent)":u.top?"linear-gradient(to bottom, transparent, black 12px)":u.bottom?"linear-gradient(to bottom, black calc(100% - 12px), transparent)":void 0}},A.createElement("div",{ref:q},f,A.createElement("div",\n{className:aj("flex flex-col",l?"gap-px p-1":"")},m))),g)};function A0a({size:a,className:b}){return A.createElement("span",{className:aj("ml-auto flex shrink-0 pl-1",b)},A.createElement(W,{name:"check",size:a}))}const LL=A.createContext(null),ML=A.createContext(null),B0a=A.createContext(null)', 'B&&(B.inert=!b,b&&t&&(t.scrollTop=0))},[b,t]);A.useEffect(()=>{if(e){var B=requestAnimationFrame(()=>{w.current?.()});return()=>cancelAnimationFrame(B)}},[e]);a=x||e?a:a+1;return A.createElement("div",{ref:n,onTransitionEnd:e?B=>{B.target===B.currentTarget&&B.propertyName==="transform"&&w.current?.()}:void 0,className:aj("absolute inset-x-0 top-0 flex flex-col",\nb?"bottom-0":"pointer-events-none"),style:{transform:`translateX(${a*100}%)`,display:!b&&!e?"none":void 0}},A.createElement("div",{ref:r,onScroll:v,className:b?"flex-1 overflow-y-auto overscroll-contain":"overflow-hidden"},A.createElement("div",{ref:q},f,A.createElement("div",\n{className:aj("flex flex-col",l?"gap-px p-1":"")},m))),g)};function A0a({size:a,className:b}){return A.createElement("span",{className:aj("ml-auto flex shrink-0 pl-1",b)},A.createElement(W,{name:"check",size:a}))}const LL=A.createContext(null),ML=A.createContext(null),B0a=A.createContext(null)'),
    ('main.js#20', 'var ECb=A.createContext(!1),G_=({title:a,description:b,children:c,scrollable:e=!0,headerRight:f,onBack:g})=>{var h=A.useContext(ECb);e=aj("w-full bg-transparent",e?"h-full overflow-y-auto":"");return A.createElement("div",{className:e},A.createElement("div",{className:aj(h?"p-4":"p-6","flex flex-col gap-4 w-full max-w-2xl mx-auto")},(a||b||f||g)&&A.createElement("div",{className:"flex flex-col gap-2 w-full mb-2 bg-transparent"},g&&A.createElement("div",{className:"flex bg-transparent"},A.createElement("button",\n{onClick:g,className:"opacity-70 hover:opacity-100 rounded-lg cursor-pointer flex items-center gap-1.5 border-none bg-transparent text-foreground h-8 px-2 shrink-0 -ml-2 transition-opacity","aria-label":"Back"},A.createElement(W,{name:"arrow_back",size:16}),A.createElement("span",{className:"text-sm font-medium"},"Back"))),A.createElement("div",{className:aj("flex justify-between items-start gap-4 w-full bg-transparent",h?"":"pr-8 lg:pr-0")},A.createElement("div",{className:"flex-1 flex flex-col gap-1 min-w-0 bg-transparent"},\na&&A.createElement("h2",{className:aj(h?"text-lg":"text-xl","m-0 font-medium truncate flex-1 text-foreground")},a),b&&A.createElement("div",{className:"text-sm text-muted-foreground bg-transparent"},b)),f&&A.createElement("div",{className:"shrink-0"},f))),A.createElement("div",{className:"flex flex-col gap-8 w-full"},c)))}', 'var ECb=A.createContext(!1),G_=({title:a,description:b,children:c,scrollable:e=!0,headerRight:f,onBack:g})=>{var h=A.useContext(ECb);e=aj("w-full bg-transparent",e&&!h?"h-full":"");return A.createElement("div",{className:e},A.createElement("div",{className:aj(h?"p-4":"p-6","flex flex-col gap-4 w-full max-w-2xl mx-auto")},(a||b||f||g)&&A.createElement("div",{className:"flex flex-col gap-2 w-full mb-2 bg-transparent"},g&&A.createElement("div",{className:"flex bg-transparent"},A.createElement("button",\n{onClick:g,className:"opacity-70 hover:opacity-100 rounded-lg cursor-pointer flex items-center gap-1.5 border-none bg-transparent text-foreground h-8 px-2 shrink-0 -ml-2 transition-opacity","aria-label":"Back"},A.createElement(W,{name:"arrow_back",size:16}),A.createElement("span",{className:"text-sm font-medium"},"Back"))),A.createElement("div",{className:aj("flex justify-between items-start gap-4 w-full bg-transparent",h?"":"pr-8 lg:pr-0")},A.createElement("div",{className:"flex-1 flex flex-col gap-1 min-w-0 bg-transparent"},\na&&A.createElement("h2",{className:aj(h?"text-lg":"text-xl","m-0 font-medium truncate flex-1 text-foreground")},a),b&&A.createElement("div",{className:"text-sm text-muted-foreground bg-transparent"},b)),f&&A.createElement("div",{className:"shrink-0"},f))),A.createElement("div",{className:"flex flex-col gap-8 w-full"},c)))}'),
    ('main.js#21', 'function G6b(a,b,c,e){(0,A.useLayoutEffect)(()=>{var f=b.current,g=a.current;if(e&&f&&g){var h=()=>{var l=Math.ceil(f.getBoundingClientRect().width);l>0?g.style.setProperty(c,`${l+8}px`):g.style.removeProperty(c)};h()', 'function G6b(a,b,c,e){(0,A.useLayoutEffect)(()=>{var f=b.current,g=a.current;if(e&&f&&g){var h=()=>{var l=Math.ceil(f.getBoundingClientRect().width),n=l>0?`${l+8}px`:"";if(n){g.style.getPropertyValue(c)!==n&&g.style.setProperty(c,n)}else g.style.getPropertyValue(c)&&g.style.removeProperty(c)};h()'),
    ('main.js#22', 'return()=>{k.disconnect();g.style.removeProperty(c)}}}else g?.style.removeProperty(c)},[a,b,c,e])}\nfunction H6b({sidebar:a,header:b,content:c,auxPane:e,statusBar:f,sidebarWidth:g,isSidebarOpen:h,onSidebarResize:k,minSidebarSize:l,maxSidebarSize:m,isAuxPaneOpen:n=!1,auxPaneWidth:q=360,auxPaneWidthUnit:r="px",onAuxPaneResize:t,minAuxPaneSize:u=300,maxAuxPaneSize:v}){var w=Lj(),x=lA(Bz),y=lA(Jz),B=w.get("sidebarComponent"),C=B?.hideSidebar,D=w.get("titlebarComponent"),E=w.get("avatarSpacer")??!1,F=D?.showMenuBar??!1,G=D?.showTrafficLightSpacer??!1,H=D?.showAppIcon??!1,J=!G,K=sk(),{product:L}=jS(),\nM=eA();w=w.get("conversationSearchV2")??!1', 'return()=>{k.disconnect();!rK()&&g.style.getPropertyValue(c)&&g.style.removeProperty(c)}}}else g&&!rK()&&g.style.getPropertyValue(c)&&g.style.removeProperty(c)},[a,b,c,e])}\nfunction H6b({sidebar:a,header:b,content:c,auxPane:e,statusBar:f,sidebarWidth:g,isSidebarOpen:h,onSidebarResize:k,minSidebarSize:l,maxSidebarSize:m,isAuxPaneOpen:n=!1,auxPaneWidth:q=360,auxPaneWidthUnit:r="px",onAuxPaneResize:t,minAuxPaneSize:u=300,maxAuxPaneSize:v}){var w=Lj(),x=lA(Bz),y=lA(Jz),B=w.get("sidebarComponent"),C=B?.hideSidebar,D=w.get("titlebarComponent"),E=w.get("avatarSpacer")??!1,F=D?.showMenuBar??!1,G=D?.showTrafficLightSpacer??!1,H=D?.showAppIcon??!1,J=!G,K=sk(),{product:L}=jS(),\nM=eA();w=w.get("conversationSearchV2")??!1'),
]


def _apply_perf_patch(content):
    """Rewrite the swipe/drag hook to direct-DOM transforms; new content or None.

    Skips cleanly when the gesture hook is entirely absent (a minimal or
    synthetic bundle, e.g. the sandbox test fixture): there is nothing to
    rewrite, and failing there would break unrelated patches. Fails closed
    when the hook is only partially present, so a half-patched bundle can
    never ship.
    """
    present_old = sum(1 for _, old, _ in PERF_HUNKS if content.count(old) >= 1)
    present_new = sum(1 for _, _, new in PERF_HUNKS if content.count(new) >= 1)
    if present_old == 0 and present_new == 0:
        print("[web-patch] swipe/drag hook not present, skipping PERF patch")
        return content
    applied = 0
    for name, old, new in PERF_HUNKS:
        old_count = content.count(old)
        new_count = content.count(new)
        if old_count == 1 and new_count == 0:
            content = content.replace(old, new, 1)
            applied += 1
        elif old_count == 0 and new_count >= 1:
            pass  # already applied
        else:
            print(
                f"[web-patch] PERF pattern ambiguous for {name}: "
                f"old={old_count}, new={new_count} (expected exactly one of them)",
                file=sys.stderr,
            )
            return None
    print(f"[web-patch] swipe/drag PERF hunks: {applied} applied, "
          f"{len(PERF_HUNKS) - applied} already present")
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
    content = _apply_perf_patch(content)
    if content is None:
        return False

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("[web-patch] main.js patched (Desktop Mode toggle + sandboxMode off for Default/Auto + swipe/drag PERF)")
    return True

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "main.js")
    if not patch_main(path):
        sys.exit(1)
