#!/bin/sh
# Build llama-server for NemoIso, pinned and static.
#
# Rewritten on 2026-10-08: the original was lost with the rest of the
# NemoIso tree. It is NOT the script the first ISO was built with.
#
#   build-llama.sh [--avx | --avx2] [PREFIX]
#
# Without --avx the build uses nothing newer than SSE4.2, so it runs on a
# Sandy Bridge Pentium or Celeron, which have no AVX (the machine Nemo is
# for). It also runs on anything newer, only slower. The first ISO shipped
# an AVX build and rebuilt on first boot where that failed (O15), which
# needed a network and half an hour on the very machines least able to
# spare them. This builds the one that always starts.
#
# --avx adds AVX and nothing else: a Sandy or Ivy Bridge Core has AVX but
# not AVX2, FMA, F16C or BMI2, which came with Haswell.
#
# --avx2 adds AVX, AVX2, FMA, F16C and BMI2 (Haswell and later), never
# AVX-512. nemo-fit uses --avx and --avx2 to build one for the CPU NemoIso
# has booted on, and keeps it on the stick.
#
# Every option that is not wanted is switched OFF by name, because the ones
# left out default to ON. The first build here left out GGML_BMI2: cmake
# reported "-msse4.2;-mbmi2", the binary was built, and it died with
# "Illegal instruction" on the Pentium B960, which has no BMI2. The
# self-test at the end is what caught it. Read cmake's "Adding CPU backend
# variant" line in the log: it lists what was really switched on.
set -eu

TAG="b11175"                    # the same build NemoDoc.ps1 pins for Windows
AVX=OFF
AVX2=OFF
PREFIX="/opt/nemo"
for arg in "$@"; do
    case "$arg" in
        --avx) AVX=ON ;;
        --avx2) AVX=ON; AVX2=ON ;;
        -*) echo "unknown option $arg" >&2; exit 2 ;;
        *) PREFIX="$arg" ;;
    esac
done

SRC="${NEMO_BUILD_DIR:-/var/tmp/nemo-llama}"
rm -rf "$SRC"
git clone --depth 1 --branch "$TAG" https://github.com/ggml-org/llama.cpp "$SRC"

cmake -S "$SRC" -B "$SRC/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF \
    -DGGML_NATIVE=OFF \
    -DGGML_SSE42=ON \
    -DGGML_AVX="$AVX" \
    -DGGML_AVX2="$AVX2" -DGGML_FMA="$AVX2" -DGGML_F16C="$AVX2" -DGGML_BMI2="$AVX2" -DGGML_AVX512=OFF \
    -DLLAMA_CURL=OFF \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON
cmake --build "$SRC/build" --target llama-server -j "$(nproc)"

install -d "$PREFIX/bin"
install -m 0755 "$SRC/build/bin/llama-server" "$PREFIX/bin/llama-server"

# A binary that does not start on this CPU is not installed quietly.
if ! "$PREFIX/bin/llama-server" --version >/dev/null 2>&1; then
    echo "llama-server was built but does not run on this CPU" >&2
    exit 1
fi
echo "llama-server $TAG installed at $PREFIX/bin/llama-server (AVX: $AVX, AVX2: $AVX2)"
rm -rf "$SRC"
