package com.agy.core;

import android.util.Log;

import com.agy.runtime.RuntimeManager;

import java.io.File;
import java.util.Map;

/** Builds the environment for the glibc core child process. */
public final class CoreEnvironment {

    private static final String TAG = "CoreEnvironment";

    private CoreEnvironment() {
    }

    /**
     * Selects $SHELL for the core. The runtime/bin bridge is a
     * #!/system/bin/sh script that sets LD_LIBRARY_PATH="$PREFIX/lib" for
     * the bionic child only and then execs the bundled Bash, so the linker
     * finds libandroid-support.so. The prefix Bash must NOT be used
     * directly: its RUNPATH points at the Termux package, and the core
     * environment deliberately has no LD_LIBRARY_PATH (see below), so the
     * linker fails and a new terminal dies with "Connection lost"
     * (upstream #36). When no usable bridge exists, Android's own sh is
     * the fallback. Package-private so unit tests can cover it without an
     * Android runtime.
     */
    static String selectShell(File runtimeBash) {
        if (runtimeBash != null && runtimeBash.isFile() && runtimeBash.canExecute()) {
            return runtimeBash.getAbsolutePath();
        }
        return "/system/bin/sh";
    }

    public static void apply(RuntimeManager rm, ProcessBuilder pb) {
        File files = rm.appContext().getFilesDir();
        File bin = rm.getBinDir();
        Map<String, String> env = pb.environment();
        // HOME is the app files dir and never a temp dir; it is stable across
        // builds so the core always finds $HOME/.gemini (token, config, chats).
        env.put("HOME", files.getAbsolutePath());
        env.put("TMPDIR", rm.appContext().getCacheDir().getAbsolutePath());
        Log.i(TAG, "core env: HOME=" + files.getAbsolutePath()
                + " appDataDir=" + rm.getAppDataDir().getAbsolutePath()
                + " projectsDir=" + rm.getProjectsDir().getAbsolutePath()
                + " TMPDIR=" + rm.appContext().getCacheDir().getAbsolutePath());
        env.put("SSL_CERT_FILE", rm.getCertFile().getAbsolutePath());
        String inheritedPath = env.get("PATH");
        env.put("PATH", bin.getAbsolutePath()
                + (inheritedPath == null || inheritedPath.isEmpty() ? "" : ":" + inheritedPath));
        // The core's PTY spawner uses $SHELL (or falls back to /bin/bash, which
        // does not exist on Android). The bridge sets the library path required
        // by the bundled Bash.
        File prefix = new File(files, com.agy.install.EnvPaths.PREFIX_DIR);
        env.put("SHELL", selectShell(new File(bin, "bash")));
        // PTY children need a terminal type, and the bootstrap prefix ships the
        // terminfo database that resolves it.
        env.put("TERM", "xterm-256color");
        File terminfo = new File(prefix, "share/terminfo");
        if (terminfo.isDirectory()) {
            env.put("TERMINFO", terminfo.getAbsolutePath());
        }
        env.put("LANG", "C.UTF-8");
        env.put("LC_ALL", "C.UTF-8");

        // Pure-Go resolver keeps DNS independent of Android's missing /etc.
        String godebug = env.get("GODEBUG");
        env.put("GODEBUG", godebug == null || godebug.isEmpty()
                ? "netdns=go" : godebug + ",netdns=go");
        // Emits "ANTIGRAVITY_OPEN_URL: <url>" directly to stdout from language_server
        // so OpenUrlWatcher captures the auth URL and opens the external browser reliably.
        env.put("ANTIGRAVITY_VSCODE_HOST", "1");
        // Configure browser and desktop environment so core OAuth/open tools find the browser
        File xdgOpen = new File(bin, "xdg-open");
        env.put("BROWSER", xdgOpen.getAbsolutePath());
        env.put("DISPLAY", ":0");
        env.put("WAYLAND_DISPLAY", "wayland-0");
        env.put("XDG_CURRENT_DESKTOP", "X-Generic");
        env.put("XDG_DATA_DIRS", rm.getRuntimeDir().getAbsolutePath());
        env.put("XDG_DATA_HOME", new File(files, ".local/share").getAbsolutePath());
        env.put("XDG_CONFIG_HOME", new File(files, ".config").getAbsolutePath());
        // The glibc loader resolves libraries via --library-path; keep bionic's out of the way.
        env.remove("LD_LIBRARY_PATH");
        // Do NOT export LD_PRELOAD into the process environment!
        // liblse_compat.so is a GLIBC library; exporting it in env causes Bionic's
        // dynamic linker to crash when executing /system/bin/sh (xdg-open, bridges, termux).
        // RuntimeManager.coreCommand() already preloads it into language_server via the
        // glibc loader's CLI argument: --preload <path>/liblse_compat.so.
        env.remove("LD_PRELOAD");
    }
}
