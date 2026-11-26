package com.agy.ui.webview;

import android.os.Build;
import android.util.Log;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.WebView;

import com.agy.runtime.RuntimeConfig;

/** Applies the full WebView settings profile (desktop UA, file access, TLS). */
public final class WebSettingsFactory {

    private static final String TAG = "WebViewHost";

    public static final String DESKTOP_UA =
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    + "Chrome/130.0.0.0 Safari/537.36 Antigravity/" + RuntimeConfig.CORE_VERSION;

    private WebSettingsFactory() {
    }

    private static String defaultUserAgent = null;

    public static void configure(WebView view) {
        WebSettings settings = view.getSettings();
        if (defaultUserAgent == null) {
            defaultUserAgent = settings.getUserAgentString();
        }
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setSupportZoom(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setSupportMultipleWindows(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(true);
        settings.setMediaPlaybackRequiresUserGesture(false);

        boolean desktop = DesktopModePrefs.isDesktopMode(view.getContext());
        applyDesktopMode(view, desktop);

        // The app document uses its pinned HTTPS loopback origin; file:// access
        // and HTTP mixed content are not needed and expand the bridge attack surface.
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true); // Needed for content:// file-picker results.
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            CookieManager.getInstance().setAcceptThirdPartyCookies(view, true);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            settings.setSafeBrowsingEnabled(true);
        }
        // Offscreen preraster: keeps tiles GPU-ready off the main thread (API 23+).
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            try {
                settings.setOffscreenPreRaster(true);
            } catch (Exception e) {
                Log.w(TAG, "setOffscreenPreRaster failed", e);
            }
        }
    }

    public static void applyDesktopMode(WebView view, boolean desktop) {
        WebSettings settings = view.getSettings();
        if (defaultUserAgent == null) {
            defaultUserAgent = settings.getUserAgentString();
        }
        settings.setUserAgentString(desktop ? DESKTOP_UA : defaultUserAgent);
        // The viewport meta tag must be honoured in normal mode too: the
        // tablet-scale web patch narrows the layout viewport through the
        // meta (width + initial-scale), and with useWideViewPort off the
        // tag is ignored so the patch would silently do nothing. On phones
        // the meta is width=device-width / initial-scale=1.0, so honouring
        // it changes nothing there; overview mode only zooms out when the
        // content is wider than the viewport, which the app layout is not.
        // (Desktop Mode still only differs by the UA string.)
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
    }
}
