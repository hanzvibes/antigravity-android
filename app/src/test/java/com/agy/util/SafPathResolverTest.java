package com.agy.util;

import java.io.File;
import java.nio.file.Files;

/**
 * Plain-JVM unit test for {@link SafPathResolver} (no Android runtime
 * needed -- the class under test has no Android imports).
 *
 * Run: bash app/src/test/run.sh
 * Or directly: javac the two files and run this class's main().
 */
public final class SafPathResolverTest {

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
        System.out.println("SafPathResolverTest");

        // isNumericId
        check("isNumericId(359524)", SafPathResolver.isNumericId("359524"));
        check("isNumericId(msd:123) is false", !SafPathResolver.isNumericId("msd:123"));
        check("isNumericId(empty) is false", !SafPathResolver.isNumericId(""));
        check("isNumericId(null) is false", !SafPathResolver.isNumericId(null));
        check("isNumericId(12a) is false", !SafPathResolver.isNumericId("12a"));

        // stripRawPrefix -- the "raw:" form already is a real path.
        equal("stripRawPrefix(raw:/a/b)",
                "/storage/emulated/0/Download/foo",
                SafPathResolver.stripRawPrefix("raw:/storage/emulated/0/Download/foo"));
        check("stripRawPrefix(primary:...) is null",
                SafPathResolver.stripRawPrefix("primary:Download") == null);
        check("stripRawPrefix(null) is null",
                SafPathResolver.stripRawPrefix(null) == null);

        // stripLeadingSlash
        equal("stripLeadingSlash(/foo)", "foo", SafPathResolver.stripLeadingSlash("/foo"));
        equal("stripLeadingSlash(foo)", "foo", SafPathResolver.stripLeadingSlash("foo"));

        // candidatesForDocumentId + firstExisting, against a real temp tree.
        File base = Files.createTempDirectory("saf-base").toFile();
        File downloadFoo = new File(new File(base, "Download"), "foo");
        if (!downloadFoo.mkdirs()) {
            throw new IllegalStateException("cannot create " + downloadFoo);
        }

        File[] primary = SafPathResolver.candidatesForDocumentId("primary:Download/foo", base);
        equal("primary: candidate count", 1, primary.length);
        equal("primary:Download/foo resolves to existing dir",
                downloadFoo.getAbsolutePath(),
                SafPathResolver.firstExisting(primary));

        File[] primaryRoot = SafPathResolver.candidatesForDocumentId("primary:", base);
        equal("primary: (empty) resolves to storage root",
                base.getAbsolutePath(),
                SafPathResolver.firstExisting(primaryRoot));

        // Regression test for upstream #41: a bare numeric Downloads ID
        // must never resolve to a fabricated path under the storage root.
        File[] numeric = SafPathResolver.candidatesForDocumentId("359524", base);
        check("numeric id 359524 has no existing candidate",
                SafPathResolver.firstExisting(numeric) == null);

        File[] missing = SafPathResolver.candidatesForDocumentId("primary:Download/nope", base);
        check("missing primary: folder resolves to null",
                SafPathResolver.firstExisting(missing) == null);

        // Volume IDs: /storage/<volume>/<sub> first, primary storage fallback second.
        File[] volume = SafPathResolver.candidatesForDocumentId("ABCD-1234:Download/foo", base);
        equal("volume candidate count", 2, volume.length);
        equal("volume candidate[0]", "/storage/ABCD-1234/Download/foo",
                volume[0].getPath());
        // /storage/ABCD-1234/... does not exist here, so the fallback wins.
        File volFallback = new File(new File(base, "Download"), "foo");
        equal("volume falls back to existing primary-storage copy",
                volFallback.getAbsolutePath(),
                SafPathResolver.firstExisting(volume));

        // downloadCandidate (MediaStore RELATIVE_PATH + DISPLAY_NAME).
        equal("downloadCandidate with relative path",
                new File(new File(new File(base, "Download"), "foo"), "bar").getPath(),
                SafPathResolver.downloadCandidate(base, "Download/foo/", "bar").getPath());
        equal("downloadCandidate without relative path",
                new File(new File(base, "Download"), "bar").getPath(),
                SafPathResolver.downloadCandidate(base, null, "bar").getPath());
        check("downloadCandidate with empty name is null",
                SafPathResolver.downloadCandidate(base, "Download/", "") == null);

        // firstExisting with no candidates.
        check("firstExisting(null) is null", SafPathResolver.firstExisting(null) == null);
        check("firstExisting(empty) is null",
                SafPathResolver.firstExisting(new File[0]) == null);

        System.out.println(failures == 0 ? "SafPathResolverTest: OK"
                : "SafPathResolverTest: " + failures + " FAILURE(S)");
        if (failures > 0) {
            System.exit(1);
        }
    }
}
