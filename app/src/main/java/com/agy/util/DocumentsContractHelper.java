package com.agy.util;

import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.DocumentsContract;
import android.provider.MediaStore;
import android.util.Log;

import java.io.File;

/**
 * Resolves Storage Access Framework (SAF) tree URIs to real filesystem paths.
 *
 * The Downloads provider is the tricky one: under its virtual Downloads
 * view it hands out numeric document IDs (e.g. {@code "359524"}),
 * {@code "msd:<id>"} IDs, or {@code "raw:/storage/..."} paths instead of
 * the usual {@code "primary:Download/<folder>"} form. The old code blindly
 * appended whatever ID it got to the primary storage root, producing paths
 * like {@code "/storage/emulated/0/359524"} that do not exist (upstream #41).
 *
 * Rules now:
 * <ul>
 * <li>{@code "raw:<path>"} is returned as-is: the provider already gave a
 *     real path.</li>
 * <li>Downloads-provider IDs are resolved through the ContentResolver
 *     (legacy {@code _data} column, then MediaStore
 *     {@code RELATIVE_PATH + DISPLAY_NAME}, then an exists()-checked
 *     {@code Download/<display name>} guess for top-level folders).</li>
 * <li>If nothing resolves, {@code null} is returned -- MainActivity
 *     already forwards null to the WebView, which is strictly better
 *     than handing the core a path that does not exist.</li>
 * <li>Every other fallback candidate is only returned when the file
 *     actually exists (see {@link SafPathResolver}).</li>
 * </ul>
 *
 * The pure path logic lives in {@link SafPathResolver} so it can be
 * unit-tested on a plain JVM; only the ContentResolver lookups need
 * Android here.
 */
public final class DocumentsContractHelper {

    private static final String TAG = "DocumentsContractHelper";

    private static final String DOWNLOADS_AUTHORITY =
            "com.android.providers.downloads.documents";
    private static final String DOWNLOADS_PUBLIC_URI =
            "content://downloads/public_downloads/";

    private DocumentsContractHelper() {
    }

    public static String resolveTreeUriToPath(Context context, Uri treeUri) {
        if (treeUri == null) {
            return null;
        }
        try {
            String documentId = DocumentsContract.getTreeDocumentId(treeUri);
            if (documentId == null || documentId.isEmpty()) {
                return null;
            }
            File baseStorage = Environment.getExternalStorageDirectory();

            String rawPath = SafPathResolver.stripRawPrefix(documentId);
            if (rawPath != null) {
                return rawPath;
            }

            if (DOWNLOADS_AUTHORITY.equals(treeUri.getAuthority())) {
                return resolveDownloadsDocument(context, documentId, baseStorage);
            }

            File[] candidates = SafPathResolver.candidatesForDocumentId(documentId, baseStorage);
            return SafPathResolver.firstExisting(candidates);
        } catch (Throwable t) {
            Log.w(TAG, "Error resolving tree uri to path: " + treeUri, t);
            return null;
        }
    }

    /**
     * Resolves a Downloads-provider document ID to a real path.
     * {@code documentId} may be numeric ({@code "359524"}), {@code "msd:<id>"},
     * or any other form the provider hands out. Returns null when the ID
     * cannot be resolved to an existing path.
     */
    private static String resolveDownloadsDocument(Context context, String documentId,
                                                   File baseStorage) {
        String numericId = documentId.startsWith("msd:")
                ? documentId.substring("msd:".length())
                : documentId;

        if (SafPathResolver.isNumericId(numericId)) {
            // 1. Legacy _data column via the public downloads URI. Still
            //    populated on many devices; may return null / throw on
            //    newer Android versions, which is fine -- we fall through.
            String dataPath = querySingleString(context,
                    Uri.parse(DOWNLOADS_PUBLIC_URI + numericId),
                    "_data", null, null);
            if (dataPath != null && !dataPath.isEmpty()) {
                File candidate = new File(dataPath);
                if (candidate.exists()) {
                    return candidate.getAbsolutePath();
                }
            }

            // 2. MediaStore (API 29+): RELATIVE_PATH + DISPLAY_NAME.
            //    Guarded by SDK_INT: the app's minSdk is 24 and
            //    MediaStore.Downloads does not exist below API 29.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                String mediaPath = resolveViaMediaStore(context, numericId, baseStorage);
                if (mediaPath != null) {
                    return mediaPath;
                }
            }
        }

        // 3. Top-level folder inside Download/: the provider's display
        //    name is enough, but only trust it when the folder really exists.
        String displayName = querySingleString(context,
                DocumentsContract.buildDocumentUri(DOWNLOADS_AUTHORITY, documentId),
                DocumentsContract.Document.COLUMN_DISPLAY_NAME, null, null);
        if (displayName != null && !displayName.isEmpty()) {
            File candidate = new File(new File(baseStorage, "Download"), displayName);
            if (candidate.exists()) {
                return candidate.getAbsolutePath();
            }
        }

        Log.w(TAG, "cannot resolve Downloads document id to a real path: " + documentId);
        return null;
    }

    private static String resolveViaMediaStore(Context context, String numericId,
                                               File baseStorage) {
        if (context == null) {
            return null;
        }
        Cursor cursor = null;
        try {
            cursor = context.getContentResolver().query(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    new String[]{
                            MediaStore.MediaColumns.RELATIVE_PATH,
                            MediaStore.MediaColumns.DISPLAY_NAME
                    },
                    MediaStore.Downloads._ID + "=?",
                    new String[]{numericId},
                    null);
            if (cursor != null && cursor.moveToFirst()) {
                String relativePath = cursor.getString(0);
                String displayName = cursor.getString(1);
                File candidate = SafPathResolver.downloadCandidate(
                        baseStorage, relativePath, displayName);
                if (candidate != null && candidate.exists()) {
                    return candidate.getAbsolutePath();
                }
            }
        } catch (Throwable t) {
            Log.w(TAG, "MediaStore lookup failed for Downloads id " + numericId, t);
        } finally {
            if (cursor != null) {
                cursor.close();
            }
        }
        return null;
    }

    /** Runs a single-column, single-row query; null when anything is missing. */
    private static String querySingleString(Context context, Uri uri, String column,
                                            String selection, String[] selectionArgs) {
        if (context == null || uri == null) {
            return null;
        }
        Cursor cursor = null;
        try {
            cursor = context.getContentResolver().query(
                    uri, new String[]{column}, selection, selectionArgs, null);
            if (cursor != null && cursor.moveToFirst()) {
                int idx = cursor.getColumnIndex(column);
                if (idx >= 0) {
                    return cursor.getString(idx);
                }
            }
        } catch (Throwable t) {
            Log.w(TAG, "query failed: " + uri, t);
        } finally {
            if (cursor != null) {
                cursor.close();
            }
        }
        return null;
    }
}
