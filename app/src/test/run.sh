#!/usr/bin/env bash
# Runs the pure-JVM unit tests for the app (no Android runtime, no device,
# no Gradle -- plain javac/java only). A JDK must be on PATH.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# SafPathResolver has no Android imports: plain compile.
javac -d "$TMP" \
    "$ROOT/app/src/main/java/com/agy/util/SafPathResolver.java" \
    "$ROOT/app/src/test/java/com/agy/util/SafPathResolverTest.java"
java -cp "$TMP" com.agy.util.SafPathResolverTest

# CoreEnvironment references Android classes, so it is compiled against
# the repo's android.jar, with the app sources on the sourcepath so its
# sibling classes (RuntimeManager, EnvPaths) resolve. BuildConfig is a
# generated class: produce it with the repo's own generator into a
# throwaway directory and add that to the sourcepath. Only selectShell()
# is exercised, which touches java.io.File alone -- no Android class is
# ever loaded at runtime.
python3 "$ROOT/modules/builder/01_gen_config.py" "$TMP/build"
javac -cp "$ROOT/tools/android.jar" \
    -sourcepath "$ROOT/app/src/main/java:$TMP/build/gen" -d "$TMP" \
    "$ROOT/app/src/main/java/com/agy/core/CoreEnvironment.java" \
    "$ROOT/app/src/test/java/com/agy/core/CoreEnvironmentTest.java"
java -cp "$TMP:$ROOT/tools/android.jar" com.agy.core.CoreEnvironmentTest
