package com.agy.util;

import java.io.File;

/**
 * Pure-Java (no Android APIs) helpers for resolving SAF document IDs to
 * filesystem paths. Split out of {@link DocumentsContractHelper} so the
 * path logic can be unit-tested on a plain JVM; the Android-only parts
 * (ContentResolver queries against the Downloads provider / MediaStore)
 * stay in the wrapper.
 *
 * Background (upstream #41): the Downloads provider hands out document
 * IDs that are not paths -- numeric IDs (e.g. {@code "359524"}),
 * {@code "msd:<id>"} IDs, or {@code "raw:/storage/..."} paths -- instead
 * of the usual {@code "primary:Download/<folder>"} form. Blindly
 * appending such an ID to the primary storage root produced paths like
 * {@code "/storage/emulated/0/359524"} that do not exist.
 */
public final class SafPathResolver {

    private SafPathResolver() {
    }

    /** True for a purely numeric document ID, e.g. {@code "359524"}. */
    public static boolean isNumericId(String s) {
        if (s == null || s.isEmpty()) {
            return false;
        }
        for (int i = 0; i < s.length(); i++) {
            if (!Character.isDigit(s.charAt(i))) {
                return false;
            }
        }
        return true;
    }

    /**
     * Strips a {@code "raw:"} prefix: the provider already gave a real
     * path, so it is returned as-is. Returns null when the ID has no
     * {@code "raw:"} prefix.
     */
    public static String stripRawPrefix(String documentId) {
        if (documentId != null && documentId.startsWith("raw:")) {
            return documentId.substring("raw:".length());
        }
        return null;
    }

    public static String stripLeadingSlash(String s) {
        if (s != null && s.startsWith("/")) {
            return s.substring(1);
        }
        return s;
    }

    /**
     * Candidate filesystem locations for a non-Downloads document ID, in
     * priority order. Callers must check {@link File#exists()} (see
     * {@link #firstExisting(File[])}) -- a candidate is never a promise
     * that the path exists.
     *
     * <ul>
     * <li>{@code "primary:<sub>"}: {@code <base>/<sub>} (empty sub-path
     *     resolves to the storage root itself).</li>
     * <li>{@code "<volume>:<sub>"}: {@code /storage/<volume>/<sub>},
     *     then {@code <base>/<sub>} as a fallback.</li>
     * <li>Anything else: {@code <base>/<id>} (last-resort fallback).</li>
     * </ul>
     */
    public static File[] candidatesForDocumentId(String documentId, File baseStorage) {
        if (documentId == null) {
            return new File[0];
        }
        if (documentId.startsWith("primary:")) {
            String subPath = stripLeadingSlash(documentId.substring("primary:".length()));
            return new File[]{new File(baseStorage, subPath)};
        }
        String[] parts = documentId.split(":", 2);
        if (parts.length > 1) {
            String volume = parts[0];
            String subPath = stripLeadingSlash(parts[1]);
            if ("primary".equalsIgnoreCase(volume)) {
                return new File[]{new File(baseStorage, subPath)};
            }
            return new File[]{
                    new File("/storage/" + volume + "/" + subPath),
                    new File(baseStorage, subPath)
            };
        }
        return new File[]{new File(baseStorage, stripLeadingSlash(documentId))};
    }

    /** Returns the absolute path of the first candidate that exists, or null. */
    public static String firstExisting(File[] candidates) {
        if (candidates == null) {
            return null;
        }
        for (File candidate : candidates) {
            if (candidate != null && candidate.exists()) {
                return candidate.getAbsolutePath();
            }
        }
        return null;
    }

    /**
     * Joins a MediaStore Downloads row into a candidate path:
     * {@code <base>/<relativePath>/<displayName>}. When the row has no
     * relative path, the file is assumed to be a top-level entry of the
     * {@code Download} folder.
     */
    public static File downloadCandidate(File baseStorage, String relativePath,
                                         String displayName) {
        if (displayName == null || displayName.isEmpty()) {
            return null;
        }
        File parent;
        if (relativePath == null || relativePath.isEmpty()) {
            parent = new File(baseStorage, "Download");
        } else {
            parent = new File(baseStorage, relativePath);
        }
        return new File(parent, displayName);
    }
}
