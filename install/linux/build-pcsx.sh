#!/bin/sh
# Build the PlayStation emulator's core (PCSX ReARMed, libretro) for
# NemoIso, pinned: Debian packages no PS1 core, so it is built here, as
# build-sd.sh builds sd-cli (owner, 2026-11-06: "add playstation also",
# "Build it into the image").
#
#   build-pcsx.sh [CORE_DIR]   installs CORE_DIR/pcsx_rearmed_libretro.so
#                              (/usr/lib/x86_64-linux-gnu/libretro, where
#                              Debian's retroarch finds its other cores)
#
# The tag is checked against the full commit after the clone, so a tag
# moved upstream stops the build; nemo/gaming.py's PS1_LINUX holds the same
# two and a test holds them together. GPL-2.0, libretro/pcsx_rearmed.
#
# Nothing newer than SSE4.2: the makefile sets no -march for x86-64, and
# its only CPU option is -mssse3 (read from a build's log, 2026-11-06, in
# WSL Debian 13: 13 s on 12 threads); its dynarec (lightrec, with GNU
# lightning) picks the CPU's instructions as it runs. The core is checked
# after the build and not installed if it would not load.
set -eu

TAG="r26l"
COMMIT="9f8b6f248e073f03c530efda7c4cc60a7e2ecafc"
CORE_DIR="/usr/lib/x86_64-linux-gnu/libretro"
for arg in "$@"; do
    case "$arg" in
        -*) echo "unknown option $arg" >&2; exit 2 ;;
        *) CORE_DIR="$arg" ;;
    esac
done

SRC="${NEMO_BUILD_DIR:-/var/tmp/nemo-pcsx}"
rm -rf "$SRC"
git clone --depth 1 --branch "$TAG" https://github.com/libretro/pcsx_rearmed "$SRC"
got="$(git -C "$SRC" rev-parse HEAD)"
if [ "$got" != "$COMMIT" ]; then
    echo "tag $TAG is commit $got, not the pinned $COMMIT: not building it" >&2
    exit 1
fi
# Its one submodule (libpicofe) is pinned by the commit above.
git -C "$SRC" submodule update --init

make -C "$SRC" -f Makefile.libretro platform=unix -j "$(nproc)"

lib="$SRC/pcsx_rearmed_libretro.so"
# A core that does not load is not installed quietly: it must export the
# libretro entry points and its libraries must all be found.
if ! nm -D --defined-only "$lib" | grep -q " retro_run$"; then
    echo "pcsx_rearmed_libretro.so was built but is not a libretro core" >&2
    exit 1
fi
if ldd "$lib" | grep -q "not found"; then
    ldd "$lib" >&2
    echo "pcsx_rearmed_libretro.so was built but needs libraries this system lacks" >&2
    exit 1
fi

install -d "$CORE_DIR"
install -m 0644 "$lib" "$CORE_DIR/pcsx_rearmed_libretro.so"
echo "pcsx_rearmed $TAG installed at $CORE_DIR/pcsx_rearmed_libretro.so"
rm -rf "$SRC"
