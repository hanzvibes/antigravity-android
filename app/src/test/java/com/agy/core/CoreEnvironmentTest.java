package com.agy.core;

import java.io.File;
import java.nio.file.Files;

/**
 * Plain-JVM unit test for {@link CoreEnvironment#selectShell(File)} (no
 * Android runtime needed -- the method under test only touches
 * java.io.File; the Android classes CoreEnvironment references are never
 * loaded by this test).
 *
 * Regression tests for upstream #36: a new terminal died with
 * "Connection lost" because $SHELL pointed at the prefix Bash directly.
 * Its RUNPATH does not include usr/lib and the core environment has no
 * LD_LIBRARY_PATH, so the linker could not find libandroid-support.so.
 * The runtime/bin bridge must be preferred: it sets LD_LIBRARY_PATH for
 * the bionic child only.
 *
 * Run: bash app/src/test/run.sh
 */
public final class CoreEnvironmentTest {

    private static int failures = 0;

    private static void check(String name, boolean condition) {
        if (condition) {
            System.out.println("  ok   " + name);
        } else {
            System.out.println("  FAIL " + name);
            failures++;
        }
    }

    private static void equal(String name, Object expected, Object actual) {
        check(name + " (expected=" + expected + ", actual=" + actual + ")",
                expected == null ? actual == null : expected.equals(actual));
    }

    public static void main(String[] args) throws Exception {
        System.out.println("CoreEnvironmentTest");

        File bin = Files.createTempDirectory("agy-bin").toFile();
        File bridge = new File(bin, "bash");

        // No bridge at all -> system shell.
        equal("missing bridge falls back to /system/bin/sh",
                "/system/bin/sh", CoreEnvironment.selectShell(bridge));
        equal("null bridge falls back to /system/bin/sh",
                "/system/bin/sh", CoreEnvironment.selectShell(null));

        // Bridge present but not executable -> system shell.
        if (!bridge.createNewFile()) {
            throw new IllegalStateException("cannot create " + bridge);
        }
        equal("non-executable bridge falls back to /system/bin/sh",
                "/system/bin/sh", CoreEnvironment.selectShell(bridge));

        // Bridge present and executable -> the bridge is $SHELL.
        if (!bridge.setExecutable(true)) {
            throw new IllegalStateException("cannot chmod +x " + bridge);
        }
        equal("executable bridge is selected as $SHELL",
                bridge.getAbsolutePath(), CoreEnvironment.selectShell(bridge));

        // A directory named "bash" is not a usable bridge.
        File dirBridge = new File(bin, "dirbash");
        if (!dirBridge.mkdir()) {
            throw new IllegalStateException("cannot mkdir " + dirBridge);
        }
        equal("directory is not a usable bridge",
                "/system/bin/sh", CoreEnvironment.selectShell(dirBridge));

        System.out.println(failures == 0 ? "CoreEnvironmentTest: OK"
                : "CoreEnvironmentTest: " + failures + " FAILURE(S)");
        if (failures > 0) {
            System.exit(1);
        }
    }
}
