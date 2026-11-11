#!/bin/sh
# Build sd-cli (stable-diffusion.cpp) for the Artist's story covers on
# NemoIso, pinned and static: the Linux counterpart of the Windows CPU build
# NemoDoc.ps1 fetches. The project publishes no Linux CPU build, so it is
# built here, as build-llama.sh builds llama-server.
#
#   build-sd.sh [PREFIX]      installs PREFIX/artist/sd/sd-cli (/opt/nemo)
#
# The same commit as the Windows zip (sd-master-3f8527a-bin-win-cpu-x64.zip,
# release master-929-3f8527a), and nemo/artist.py's ENGINE_COMMIT; a test
# holds the three together. The tag is checked against the full commit
# after the clone, so a tag moved upstream stops the build.
#
# Nothing newer than SSE4.2, every newer option switched OFF by name, as in
# build-llama.sh: an option left out defaults to ON, and the first llama.cpp
# build here died with "Illegal instruction" on the Pentium B960 for want of
# GGML_BMI2=OFF. WebP and WebM output are left out (a cover is a PNG), and
# with them the submodules they need: only ggml is fetched.
set -eu

TAG="master-929-3f8527a"
COMMIT="3f8527a46c54ecf4cb4ed6003da8e8982283c73c"
PREFIX="/opt/nemo"
for arg in "$@"; do
    case "$arg" in
        -*) echo "unknown option $arg" >&2; exit 2 ;;
        *) PREFIX="$arg" ;;
    esac
done

SRC="${NEMO_BUILD_DIR:-/var/tmp/nemo-sd}"
rm -rf "$SRC"
git clone --depth 1 --branch "$TAG" https://github.com/leejet/stable-diffusion.cpp "$SRC"
got="$(git -C "$SRC" rev-parse HEAD)"
if [ "$got" != "$COMMIT" ]; then
    echo "tag $TAG is commit $got, not the pinned $COMMIT: not building it" >&2
    exit 1
fi
git -C "$SRC" submodule update --init --depth 1 ggml

cmake -S "$SRC" -B "$SRC/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF -DSD_BUILD_SHARED_LIBS=OFF \
    -DSD_WEBP=OFF -DSD_WEBM=OFF \
    -DGGML_NATIVE=OFF \
    -DGGML_SSE42=ON \
    -DGGML_AVX=OFF -DGGML_AVX_VNNI=OFF \
    -DGGML_AVX2=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF -DGGML_BMI2=OFF -DGGML_AVX512=OFF
cmake --build "$SRC/build" --target sd-cli -j "$(nproc)"

install -d "$PREFIX/artist/sd"
install -m 0755 "$SRC/build/bin/sd-cli" "$PREFIX/artist/sd/sd-cli"
echo "$TAG" > "$PREFIX/artist/sd/build.txt"

# A binary that does not start on this CPU is not installed quietly.
if ! "$PREFIX/artist/sd/sd-cli" --version >/dev/null 2>&1; then
    echo "sd-cli was built but does not run on this CPU" >&2
    exit 1
fi
echo "sd-cli $TAG installed at $PREFIX/artist/sd/sd-cli"
rm -rf "$SRC"
