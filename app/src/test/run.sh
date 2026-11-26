#!/usr/bin/env bash
# Runs the pure-JVM unit test for SafPathResolver (no Android runtime,
# no device, no Gradle -- plain javac/java only).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
javac -d "$TMP" \
    "$ROOT/app/src/main/java/com/agy/util/SafPathResolver.java" \
    "$ROOT/app/src/test/java/com/agy/util/SafPathResolverTest.java"
java -cp "$TMP" com.agy.util.SafPathResolverTest
