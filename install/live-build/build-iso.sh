#!/bin/sh
# Build the NemoIso live image: Debian 13 (trixie), XFCE, Nemo installed.
#
# Rewritten on 2026-10-08. The original build script was lost; this is a
# new build, not a reconstruction of the first image. What it makes:
#   - a hybrid ISO that boots from a USB stick or a DVD, BIOS or UEFI,
#     into a live XFCE desktop, with nothing written to the machine's disk;
#   - Nemo in /opt/nemo (source, a venv, llama-server built without AVX),
#     `nemodoc` on the path and Nemo in the applications menu;
#   - a list of the hashes of Nemo's files, which nemodoc compares on
#     every run;
#   - wifi for a phone's hotspot (and USB tethering), and a boot entry that
#     keeps changes on a "persistence" partition of the stick, which Rufus
#     can make.
# What it does not make, and the first image had: an installer to disk
# with full-disk encryption, boot-chain tamper evidence, and a signed
# integrity manifest. And no language model is in the image (6.5 GB):
# `nemodoc --models` fetches them. Nor is the Artist's image model (2 GB):
# its engine, sd-cli, is built into the image, and nemodoc links the model
# from the Windows disk or fetches it (see "the Artist" below).
#
#   sudo ./build-iso.sh [--minimal] [--no-llama] [--no-tools] [--no-artist]
#                       [--no-ps1] [--work DIR] [--out FILE]
#
#   --minimal   no desktop, no llama.cpp, no tools: a console image, to
#               prove the boot chain in minutes rather than hours
#   --no-tools  leave out what Nemo's design steps run (KiCad, SKiDL,
#               WireViz, CadQuery, PlatformIO with the ESP32 toolchain).
#               Nemo still starts without them; each step that needs one
#               says so and skips. They roughly treble the image.
#   --no-artist leave out sd-cli, the story covers' engine; a cover then
#               says it is not installed
#   --no-ps1    leave out the PlayStation's core (built, not packaged);
#               the PlayStation emulator then says its core is missing
#
# It does the steps itself (debootstrap, chroot, mksquashfs, xorriso)
# rather than through live-build, because it has to run under WSL 1, the
# only Linux the machine it was written on could run (virtualisation was
# off in its firmware). live-build stops there at systemd: WSL 1's kernel
# has no open-file-description locks, which systemd-sysusers takes on
# /etc/passwd. So under WSL 1, and only there, a stand-in creates the
# system users during the build, and the real program is put back before
# the image is packed.
#
# Needs, on the building machine: debootstrap squashfs-tools xorriso
# isolinux syslinux-common grub-efi-amd64-bin grub-common dosfstools
# mtools git, and a network. As root.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
WORK="/var/tmp/nemo-iso"
OUT="$REPO/NemoIso.iso"
MIRROR="http://deb.debian.org/debian"
TOOLS=1; MINIMAL=0; LLAMA=1; ARTIST=1; PS1=1
LLAMA_TAG="b11175"
while [ $# -gt 0 ]; do
    case "$1" in
        --no-tools) TOOLS=0 ;;
        --minimal) MINIMAL=1; LLAMA=0; TOOLS=0; ARTIST=0; PS1=0 ;;
        --no-llama) LLAMA=0 ;;
        --no-artist) ARTIST=0 ;;
        --no-ps1) PS1=0 ;;
        --work) shift; WORK="$1" ;;
        --out)  shift; OUT="$1" ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
for tool in debootstrap mksquashfs xorriso grub-mkstandalone mkfs.vfat mcopy git; do
    command -v "$tool" >/dev/null 2>&1 || { echo "missing: $tool" >&2; exit 1; }
done

ROOT="$WORK/root"
ISO="$WORK/iso"
WSL1=0
case "$(uname -r)" in *Microsoft*) WSL1=1 ;; esac      # WSL 2 says "microsoft-standard"

say() { printf '\n== %s  [%s]\n' "$*" "$(date '+%H:%M:%S')"; }
in_root() { chroot "$ROOT" env DEBIAN_FRONTEND=noninteractive LC_ALL=C HOME=/root "$@"; }
unmount() {
    for m in dev/pts proc sys; do umount "$ROOT/$m" 2>/dev/null || true; done
}
trap unmount EXIT

say "a clean start in $WORK"
unmount
rm -rf "$WORK"
mkdir -p "$ROOT" "$ISO/live" "$ISO/isolinux" "$ISO/EFI/BOOT" "$ISO/boot/grub"

say "the base system"
debootstrap --variant=minbase trixie "$ROOT" "$MIRROR"

say "prepared for installing into"
mount -t proc proc "$ROOT/proc"
mount -t sysfs sys "$ROOT/sys" 2>/dev/null || true
mount -t devpts devpts "$ROOT/dev/pts" 2>/dev/null || true
cp /etc/resolv.conf "$ROOT/etc/resolv.conf"
# non-free: only for the Genesis Plus GX core (Mega Drive, Master System;
# nemo/gaming.py), which Debian files there; nothing else comes from it.
echo "deb $MIRROR trixie main contrib non-free non-free-firmware" > "$ROOT/etc/apt/sources.list"
echo "deb http://security.debian.org/debian-security trixie-security main contrib non-free-firmware" \
    >> "$ROOT/etc/apt/sources.list"
# No service is started inside a chroot that is being built.
printf '#!/bin/sh\nexit 101\n' > "$ROOT/usr/sbin/policy-rc.d"
chmod +x "$ROOT/usr/sbin/policy-rc.d"
echo 'APT::Install-Recommends "false";' > "$ROOT/etc/apt/apt.conf.d/90nemo"

if [ "$WSL1" -eq 1 ]; then
    say "WSL 1: a stand-in for systemd-sysusers while building"
    in_root dpkg-divert --local --rename --add /usr/bin/systemd-sysusers
    cat > "$ROOT/usr/bin/systemd-sysusers" <<'EOF'
#!/bin/sh
# Stands in for systemd-sysusers during an image build under WSL 1, whose
# kernel lacks the lock the real one takes. Creates the groups and users
# the sysusers.d files name, with whatever ids are free. Removed, and the
# real program put back, before the image is packed.
for f in /usr/lib/sysusers.d/*.conf /etc/sysusers.d/*.conf; do
    [ -f "$f" ] || continue
    while read -r kind name id rest; do
        case "$kind" in
            g) getent group "$name" >/dev/null || groupadd -r "$name" ;;
            u|u!)
                getent group "$name" >/dev/null || groupadd -r "$name"
                getent passwd "$name" >/dev/null || \
                    useradd -r -g "$name" -d / -s /usr/sbin/nologin "$name" ;;
            m)
                getent group "$id" >/dev/null || groupadd -r "$id"
                getent passwd "$name" >/dev/null && usermod -a -G "$id" "$name" ;;
        esac
    done < "$f"
done 2>/dev/null
exit 0
EOF
    chmod +x "$ROOT/usr/bin/systemd-sysusers"
fi

say "kernel, init and live boot"
in_root apt-get update -q
# user-setup is what live-config makes the live user with. It is only a
# Recommends, and without it the first image booted to a login prompt that
# no one could log in at.
in_root apt-get install -y -q linux-image-amd64 systemd-sysv live-boot live-config \
    live-config-systemd user-setup sudo ca-certificates curl git python3 python3-venv python3-pip \
    python3-setuptools python3-wheel python3-tk python3-yaml python3-cryptography \
    python3-pypdf graphviz

# zram (owner, 2026-11-04: "add zram to nemoiso"). A live boot has no swap at
# all, so on 8 GB a model, KiCad and a browser together meet the OOM killer.
# zram-tools makes a compressed swap device in RAM at boot: pages the system
# would otherwise have to drop are kept compressed instead. lz4 (Debian's
# default) rather than zstd: it costs the B960's two threads less, and they
# are busy with the model. PERCENT=50 is the device's size, 4 GB on 8; what
# it holds is compressed, so it takes less than that. vm.swappiness is left
# at Debian's 60: a value for zram should come from measuring it on the
# AH531, which has not been done (O37, nemo-bench).
in_root apt-get install -y -q zram-tools
cat > "$ROOT/etc/default/zramswap" <<'EOF'
# Nemo (build-iso.sh): compressed swap in RAM, the live system's only swap.
ALGO=lz4
PERCENT=50
PRIORITY=100
EOF
in_root systemctl enable zramswap.service

if [ "$MINIMAL" -eq 0 ]; then
    say "the desktop"
    in_root apt-get install -y -q xorg xfce4 xfce4-terminal lightdm lightdm-gtk-greeter \
        network-manager network-manager-gnome firmware-linux-free mousepad \
        build-essential cmake desktop-base
    # A web browser (owner's request, 2026-10-19), and xdg-open (D190). With
    # Recommends off the image had neither, and everything Nemo opens goes
    # through xdg-open: a project's files, a story's folder, the
    # Researcher's datasheet links. None of it could open on the stick.
    in_root apt-get install -y -q firefox-esr xdg-utils
    in_root update-alternatives --set x-www-browser /usr/bin/firefox-esr || true
    in_root xdg-settings set default-web-browser firefox-esr.desktop 2>/dev/null || true
    # Wifi, for a phone's hotspot. The first images had NetworkManager and
    # nothing it needs to join a wifi network: wpasupplicant is only one of
    # its Recommends, and the AH531's card, an Intel Centrino Wireless-N
    # 1030 (8086:008a, the iwlwifi driver), will not start without Intel's
    # firmware. Its wired card, a Realtek RTL8168 (r8169), wants
    # firmware-realtek. The other firmware is for the wifi cards most often
    # found in laptops of its age. USB tethering needs no package: the
    # kernel has rndis_host and cdc_ncm. ntfs-3g reads the Windows disk.
    in_root apt-get install -y -q wpasupplicant wireless-regdb iw rfkill \
        firmware-iwlwifi firmware-realtek firmware-atheros firmware-brcm80211 \
        firmware-misc-nonfree ntfs-3g
    # D179: joining a network from the desktop. On the AH531 (2026-10-17)
    # it said "Not authorized to control networking": with Recommends off,
    # neither polkitd (which grants the permission) nor libpam-systemd
    # (which makes the desktop an active session to grant it to) was in the
    # image, and NetworkManager refuses everyone but root without them. The
    # rule lets the live user, who is in the sudo group, manage networks
    # whatever logind thinks of the session.
    in_root apt-get install -y -q polkitd libpam-systemd
    mkdir -p "$ROOT/etc/polkit-1/rules.d"
    cat > "$ROOT/etc/polkit-1/rules.d/50-nemo-network.rules" <<'EOF'
polkit.addRule(function(action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager.") == 0 &&
        subject.isInGroup("sudo")) {
        return polkit.Result.YES;
    }
});
EOF
    # D180: Shut Down, Restart and Suspend on the desktop did nothing on the
    # AH531 (2026-10-17). They ask systemd-logind, which asks polkit, and the
    # image had no polkitd (D179). With it, logind allows an active local
    # session; this rule allows the live user whatever logind thinks of the
    # session, as for the network. A clean shutdown also runs the save to
    # the stick (nemo-sync-shutdown.service).
    cat > "$ROOT/etc/polkit-1/rules.d/50-nemo-power.rules" <<'EOF'
polkit.addRule(function(action, subject) {
    if ((action.id.indexOf("org.freedesktop.login1.power-off") == 0 ||
         action.id.indexOf("org.freedesktop.login1.reboot") == 0 ||
         action.id.indexOf("org.freedesktop.login1.suspend") == 0 ||
         action.id.indexOf("org.freedesktop.login1.hibernate") == 0) &&
        subject.isInGroup("sudo")) {
        return polkit.Result.YES;
    }
});
EOF
fi

say "Nemo itself, from git"
# A commit, not a working tree: nothing untracked can get into the image.
mkdir -p "$ROOT/opt/nemo/app"
git -C "$REPO" archive HEAD | tar -x -C "$ROOT/opt/nemo/app"
for f in nemodoc nemo-fit build-llama.sh build-sd.sh build-pcsx.sh fetch-models.sh; do
    install -m 0755 "$REPO/install/linux/$f" "$ROOT/opt/nemo/app/$f"
done
git -C "$REPO" rev-parse HEAD > "$ROOT/opt/nemo/COMMIT"
# Its time too: nemo.update offers a NemoWin.zip on the Windows disk only if newer.
git -C "$REPO" log -1 --format=%ct HEAD > "$ROOT/opt/nemo/COMMIT_TIME"
in_root python3 -m venv --system-site-packages /opt/nemo/venv
in_root /opt/nemo/venv/bin/pip install --no-deps --no-build-isolation --quiet /opt/nemo/app
# pip builds in the source folder and leaves its workings there. They are
# not Nemo's files, and the first image's hash list had 84 of them in it.
rm -rf "$ROOT/opt/nemo/app/build" "$ROOT"/opt/nemo/app/*.egg-info
ln -sf /opt/nemo/app/nemodoc "$ROOT/usr/local/bin/nemodoc"
ln -sf /opt/nemo/venv/bin/nemo "$ROOT/usr/local/bin/nemo"
mkdir -p "$ROOT/usr/share/applications"
cat > "$ROOT/usr/share/applications/nemo.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Nemo
Comment=Design and workshop assistant
Exec=/opt/nemo/app/nemodoc
Terminal=false
Categories=Development;Electronics;
EOF
# The same check nemodoc makes before it starts Nemo, in a window that
# stays open, so what an image has and lacks can be read on the machine.
cat > "$ROOT/usr/share/applications/nemo-check.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Nemo: check this machine
Comment=What Nemo has here and what it lacks
Exec=xfce4-terminal --hold --title "Nemo: check" -x /opt/nemo/app/nemodoc --check-only
Terminal=false
Categories=Development;Electronics;
EOF
# Work kept on the stick (owner's request, 2026-10-17). The home folder is
# in memory on a live system; nemo-sync copies ~/nemo-projects and
# ~/nemo-stories to NemoData on the boot stick every two minutes and at
# shutdown, and nemodoc copies them back at login. Only this one script may
# be run as root without a password, and only by the sudo group.
in_root apt-get install -y -q rsync
install -m 0755 "$REPO/install/linux/nemo-sync" "$ROOT/usr/local/sbin/nemo-sync"
mkdir -p "$ROOT/etc/sudoers.d"
echo '%sudo ALL=(root) NOPASSWD: /usr/local/sbin/nemo-sync' > "$ROOT/etc/sudoers.d/nemo-sync"
chmod 0440 "$ROOT/etc/sudoers.d/nemo-sync"
mkdir -p "$ROOT/etc/systemd/system"
cat > "$ROOT/etc/systemd/system/nemo-sync.service" <<'EOF'
[Unit]
Description=Keep Nemo's work on the USB stick

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/nemo-sync save nemo
EOF
cat > "$ROOT/etc/systemd/system/nemo-sync.timer" <<'EOF'
[Unit]
Description=Keep Nemo's work on the USB stick every two minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=2min

[Install]
WantedBy=timers.target
EOF
# Stopped, and so run, at shutdown, before the stick is unmounted.
cat > "$ROOT/etc/systemd/system/nemo-sync-shutdown.service" <<'EOF'
[Unit]
Description=Keep Nemo's work on the USB stick at shutdown
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/true
ExecStop=/usr/local/sbin/nemo-sync save nemo

[Install]
WantedBy=multi-user.target
EOF
in_root systemctl enable nemo-sync.timer nemo-sync-shutdown.service
# Nemo opens by itself when the desktop starts, at its prompt window.
mkdir -p "$ROOT/etc/xdg/autostart"
cat > "$ROOT/etc/xdg/autostart/nemo.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Nemo
Comment=Opens Nemo's prompt window when the desktop starts
Exec=/opt/nemo/app/nemodoc --prompt
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
# Installed and importable, from / and with -I, as nemodoc checks it (D51).
in_root sh -c 'cd / && /opt/nemo/venv/bin/python -I -c "import nemo; print(nemo.__version__)"'

# Speaking to Nemo (owner's redesign, 2026-10-17): offline, with Vosk and its
# small English model. The hash is of the file fetched on 2026-10-17 from the
# Vosk project's own site (alphacephei.com); it publishes none to check
# against, so this pins that download rather than vouching for it.
say "speech: Vosk and its small English model, and the espeak-ng voice"
# espeak-ng: the Linguist's voice (nemo/voice.py, 2026-10-21; not yet built into an image).
in_root apt-get install -y -q alsa-utils unzip espeak-ng
in_root /opt/nemo/venv/bin/pip install --quiet vosk

# The Theatre and Gaming (2026-10-21; not yet built into an image). VLC
# plays here, Chromium casts websites with its own Cast button, pychromecast
# casts the owner's files (nemo/cast.py). RetroArch with Debian's own cores:
# NES, SNES, Game Boy, Game Boy Advance from main, Mega Drive and Master
# System (Genesis Plus GX) from non-free; Debian packages no Atari 2600 core
# (nemo/gaming.py says so). NOT YET IN A BUILT IMAGE (2026-10-22).
say "theatre and gaming: VLC, Chromium, pychromecast, RetroArch"
in_root apt-get install -y -q vlc chromium retroarch libretro-nestopia     libretro-bsnes-mercury-performance libretro-gambatte libretro-mgba libretro-genesisplusgx ffmpeg
in_root /opt/nemo/venv/bin/pip install --quiet "pychromecast==14.0.10"
# The Science department (nemo/science.py): the versions NemoDoc.ps1 pins.
say "science: sympy, Pint, openpyxl"
in_root /opt/nemo/venv/bin/pip install --quiet --no-deps "openpyxl==3.1.5" "et-xmlfile==2.0.0" "sympy==1.14.0" "mpmath==1.3.0" "Pint==0.26.2" "flexcache==0.3" "flexparser==0.4" "platformdirs==4.13.5" "typing_extensions==4.16.0"
VOSK_MODEL=vosk-model-small-en-us-0.15
VOSK_SHA=30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498
# Inside the image, where curl and unzip are: the building machine need not
# have them (the WSL 1 build host had no curl, and the first build with this
# step stopped here).
in_root curl -sSfL -o "/var/tmp/$VOSK_MODEL.zip" "https://alphacephei.com/vosk/models/$VOSK_MODEL.zip"
in_root sh -c "echo '$VOSK_SHA  /var/tmp/$VOSK_MODEL.zip' | sha256sum -c -"
mkdir -p "$ROOT/opt/nemo/speech"
in_root unzip -q -o "/var/tmp/$VOSK_MODEL.zip" -d /opt/nemo/speech
rm -f "$ROOT/var/tmp/$VOSK_MODEL.zip"
# The recogniser loads and hears the test recording in the image (D51's way:
# from /, with -I), so a build whose speech cannot work says so here.
in_root sh -c 'cd / && /opt/nemo/venv/bin/python -I -c "from pathlib import Path; from nemo import speech; print(\"speech heard:\", speech.transcribe(Path(\"/opt/nemo/app/tests/data/speech-lamp.wav\")))"'

if [ "$TOOLS" -eq 1 ]; then
    say "the tools Nemo's steps run: KiCad, and the numeric packages Debian has"
    in_root apt-get install -y -q kicad kicad-symbols kicad-footprints \
        python3-numpy python3-scipy python3-rtree python3-trimesh libgl1 libxrender1
    # FreeCAD (owner, 2026-10-31): for hand edits. Optional, so not fatal, as
    # a rebuild is hours. About 1.4 GB installed, measured on a Debian 13
    # with no desktop. The squashfs must stay under FAT32's 4 GB a file; not
    # yet built with it.
    in_root apt-get install -y -q freecad || echo "apt could not install freecad"
    say "and those Debian has not: SKiDL, WireViz, CadQuery, PlatformIO"
    # One at a time, and none of them fatal: what did not install is found
    # and written down below, and a rebuild is hours.
    for pkg in skidl wireviz platformio cadquery; do
        in_root /opt/nemo/venv/bin/pip install --no-cache-dir --quiet "$pkg" \
            || echo "pip could not install $pkg"
    done
    ln -sf /opt/nemo/venv/bin/pio "$ROOT/usr/local/bin/pio"
    say "the ESP32 toolchain, by building what Nemo builds"
    # PlatformIO fetches a board's compiler and framework the first time it
    # builds for it. A live image forgets its home at every boot, so they
    # are fetched now, into the image, by compiling the same project file
    # Nemo's firmware step writes. If this builds, that step can.
    PIO_HOME=/opt/nemo/platformio
    mkdir -p "$ROOT/var/tmp/piotest/src"
    # The platform is pinned, as Nemo pins it (nemo/offline.py ESP32_PLATFORM,
    # D196): unpinned, this fetched 8.0.0 on 2026-10-20 and its compilers
    # took the image past 2.9 GB.
    printf '[env:esp32dev]\nplatform = espressif32@7.1.3\nboard = esp32dev\nframework = arduino\nmonitor_speed = 115200\nbuild_type = release\n' \
        > "$ROOT/var/tmp/piotest/platformio.ini"
    printf '#include <Arduino.h>\n#include <Wire.h>\nvoid setup() { Serial.begin(115200); Wire.begin(21, 22); }\nvoid loop() {}\n' \
        > "$ROOT/var/tmp/piotest/src/main.cpp"
    in_root env PLATFORMIO_CORE_DIR="$PIO_HOME" /opt/nemo/venv/bin/pio run -d /var/tmp/piotest \
        > "$WORK/pio-build.log" 2>&1 && PIO_OK=1 || PIO_OK=0
    tail -4 "$WORK/pio-build.log"
    rm -rf "$ROOT/var/tmp/piotest"
    chmod -R a+rwX "$ROOT$PIO_HOME" 2>/dev/null || true
    echo "PLATFORMIO_CORE_DIR=$PIO_HOME" >> "$ROOT/etc/environment"
    say "the Reverse Engineer's tools: Node.js, REA, Java 21, Ghidra"
    # Owner, 2026-11-03: "add to stick all needed for rea to work". None of it
    # fatal: what did not arrive is written down below. Debian 13's nodejs is
    # 20, older than REA 6.7.0 accepts (22.19, 24.11 or 26), so Node.js's own
    # build, pinned and checked by its published sha256.
    NODE_V=v24.22.2
    NODE_SHA=48cc0e21e048790e54c0cf5749c2725005313d652651c40b7a21feb9697aaf75
    mkdir -p "$ROOT/opt/nemo/tools"
    if in_root curl -sSfL -o /var/tmp/node.tar.xz "https://nodejs.org/dist/$NODE_V/node-$NODE_V-linux-x64.tar.xz" \
        && in_root sh -c "echo '$NODE_SHA  /var/tmp/node.tar.xz' | sha256sum -c -"; then
        in_root tar -xJf /var/tmp/node.tar.xz -C /opt/nemo/tools
        for b in node npm npx; do
            ln -sf "/opt/nemo/tools/node-$NODE_V-linux-x64/bin/$b" "$ROOT/usr/local/bin/$b"
        done
        # The same REA as on Windows. Its native parts are per system, so it is
        # installed here, not copied from C:\Nemo\tools\rea.
        in_root npm install --prefix /opt/nemo/tools/rea --omit=dev --no-fund --no-audit \
            --loglevel=error "rea-agents@6.7.0" || echo "npm could not install REA"
        ln -sf /opt/nemo/tools/rea/node_modules/.bin/rea "$ROOT/usr/local/bin/rea"
        rm -rf "$ROOT/root/.npm"
    else
        echo "Node.js $NODE_V did not download or did not match its sha256"
    fi
    rm -f "$ROOT/var/tmp/node.tar.xz"
    in_root apt-get install -y -q openjdk-21-jdk-headless || echo "apt could not install Java 21"
    # Ghidra is Java with its native parts for every system in the one
    # release, so the copy already in C:\Nemo\tools serves; Windows' parts left out.
    GHIDRA_SRC="$(ls -d "$REPO"/../tools/ghidra_12.1.4_PUBLIC 2>/dev/null || true)"
    if [ -n "$GHIDRA_SRC" ]; then
        cp -r "$GHIDRA_SRC" "$ROOT/opt/nemo/tools/"
        G="$ROOT/opt/nemo/tools/ghidra_12.1.4_PUBLIC"
        find "$G" -type d -name win_x86_64 -prune -exec rm -rf {} +
        find "$G" -type f \( -name '*.bat' -o -name '*.exe' -o -name '*.dll' \) -delete
        chmod -R a+rX,go-w "$G"
    else
        echo "Ghidra 12.1.4 is not in C:\\Nemo\\tools; left out"
    fi
    echo "GHIDRA_INSTALL_DIR=/opt/nemo/tools/ghidra_12.1.4_PUBLIC" >> "$ROOT/etc/environment"
    # The Workshop's drawings (nemo/drawings.py): CADCraft's Linux build,
    # pinned and checked by GitHub's sha256 (drawings.SOURCES; a test holds
    # them together). Its CLI was run as a Westmere and as a Sandy Bridge
    # without AVX under QEMU (2026-11-11): it draws, exports and reads back.
    CAD_V=0.19.0
    CAD_SHA=a654df8c3e447c62c490c0a8aad8c42a9fafab010ca4d25bc3504ed45b3c8f51
    if in_root curl -sSfL -o /var/tmp/cadcraft.tar.gz \
            "https://github.com/storytold/cadcraft/releases/download/v$CAD_V/cadcraft-$CAD_V-linux-x86_64.tar.gz" \
        && in_root sh -c "echo '$CAD_SHA  /var/tmp/cadcraft.tar.gz' | sha256sum -c -"; then
        in_root tar -xzf /var/tmp/cadcraft.tar.gz -C /var/tmp
        mkdir -p "$ROOT/opt/nemo/cadcraft"
        install -m 0755 "$ROOT/var/tmp/cadcraft-$CAD_V-linux-x86_64/bin/cadcraft-cli" "$ROOT/opt/nemo/cadcraft/cadcraft-cli"
        cp "$ROOT/var/tmp/cadcraft-$CAD_V-linux-x86_64/share/doc/cadcraft/"LICENSE* "$ROOT/opt/nemo/cadcraft/" 2>/dev/null || true
        rm -rf "$ROOT/var/tmp/cadcraft-$CAD_V-linux-x86_64"
    else
        echo "CADCraft $CAD_V did not download or did not match its sha256"
    fi
    rm -f "$ROOT/var/tmp/cadcraft.tar.gz"
    # Books and the pack PDF (nemo/books.py): WordCraft's Linux build, pinned
    # the same way (books.SOURCES). Its CLI was run as a Westmere and as a
    # Sandy Bridge without AVX under QEMU (2026-11-11). The whole folder: the
    # CLI may need what is beside it.
    WC_V=0.17.0
    WC_SHA=9c744c0c31a3ce25df82680fc75e645d682846faccbe103f4f91a758b19f3687
    if in_root curl -sSfL -o /var/tmp/wordcraft.tar.gz \
            "https://github.com/storytold/wordcraft/releases/download/v$WC_V/wordcraft-$WC_V-linux-x86_64.tar.gz" \
        && in_root sh -c "echo '$WC_SHA  /var/tmp/wordcraft.tar.gz' | sha256sum -c -"; then
        in_root tar -xzf /var/tmp/wordcraft.tar.gz -C /var/tmp
        rm -rf "$ROOT/opt/nemo/wordcraft"
        mkdir -p "$ROOT/opt/nemo/wordcraft"
        install -m 0755 "$ROOT/var/tmp/wordcraft-$WC_V-linux-x86_64/bin/wordcraft-cli" "$ROOT/opt/nemo/wordcraft/wordcraft-cli"
        cp "$ROOT/var/tmp/wordcraft-$WC_V-linux-x86_64/share/doc/wordcraft/"LICENSE* "$ROOT/opt/nemo/wordcraft/" 2>/dev/null || true
        rm -rf "$ROOT/var/tmp/wordcraft-$WC_V-linux-x86_64"
    else
        echo "WordCraft $WC_V did not download or did not match its sha256"
    fi
    rm -f "$ROOT/var/tmp/wordcraft.tar.gz"
    echo "JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64" >> "$ROOT/etc/environment"
    # What is there and what is not, written into the image and shown here.
    # Not fatal: a missing tool makes one step skip, and a rebuild is hours.
    {
        echo "Tools in this image, checked when it was built on $(date '+%Y-%m-%d'):"
        for mod in skidl wireviz cadquery trimesh numpy scipy rtree; do
            if in_root sh -c "cd / && /opt/nemo/venv/bin/python -c 'import $mod' >/dev/null 2>&1"; then
                echo "  ok       python: $mod"
            else
                echo "  MISSING  python: $mod (does not import)"
            fi
        done
        for tool in kicad-cli dot pio firefox-esr xdg-open freecad node rea java; do
            if in_root sh -c "command -v $tool >/dev/null 2>&1"; then echo "  ok       $tool"
            else echo "  MISSING  $tool"; fi
        done
        if in_root /opt/nemo/cadcraft/cadcraft-cli --version >/dev/null 2>&1; then echo "  ok       cadcraft-cli"
        else echo "  MISSING  cadcraft-cli"; fi
        if in_root /opt/nemo/wordcraft/wordcraft-cli --version >/dev/null 2>&1; then echo "  ok       wordcraft-cli"
        else echo "  MISSING  wordcraft-cli"; fi
        if [ -x "$ROOT/opt/nemo/tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless" ]; then echo "  ok       ghidra"
        else echo "  MISSING  ghidra"; fi
        if [ "$PIO_OK" -eq 1 ]; then echo "  ok       an ESP32 firmware compiled with the toolchain in the image"
        else echo "  MISSING  the ESP32 toolchain: the test build failed (see the build's pio-build.log)"; fi
    } > "$ROOT/opt/nemo/TOOLS.txt"
    cat "$ROOT/opt/nemo/TOOLS.txt"
fi

if [ "$LLAMA" -eq 1 ]; then
    say "llama-server, pinned and static, nothing newer than SSE4.2 (O15)"
    in_root git clone --depth 1 --branch "$LLAMA_TAG" https://github.com/ggml-org/llama.cpp /var/tmp/llama
    in_root cmake -S /var/tmp/llama -B /var/tmp/llama/build -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF -DGGML_SSE42=ON \
        -DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF -DGGML_BMI2=OFF \
        -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF
    in_root sh -c 'cmake --build /var/tmp/llama/build --target llama-server -j "$(nproc)"'
    install -D -m 0755 "$ROOT/var/tmp/llama/build/bin/llama-server" "$ROOT/opt/nemo/bin/llama-server"
    rm -rf "$ROOT/var/tmp/llama"
    in_root /opt/nemo/bin/llama-server --version
    # D176: on the PATH, like nemo and nemodoc. Nemo runs it by name; in
    # /opt/nemo/bin alone the first real run could not load a model.
    ln -sf /opt/nemo/bin/llama-server "$ROOT/usr/local/bin/llama-server"
fi

if [ "$ARTIST" -eq 1 ]; then
    # Story covers (the Artist, 2026-10-20). stable-diffusion.cpp publishes
    # no Linux CPU build, so sd-cli is built here from the commit of the
    # Windows build NemoDoc.ps1 fetches, nothing newer than SSE4.2, by the
    # same script nemodoc names (build-sd.sh). The model files are not put
    # in the image: 2 GB more would take the squashfs near the 4 GB a FAT32
    # stick holds in one file. nemodoc links them read-only from the
    # Windows disk (Nemo/artist there) or, with --models, fetches them.
    say "the Artist's engine: sd-cli, pinned and static, nothing newer than SSE4.2"
    in_root env NEMO_BUILD_DIR=/var/tmp/nemo-sd /opt/nemo/app/build-sd.sh /opt/nemo
    in_root /opt/nemo/artist/sd/sd-cli --version
    # The live user adds the model files here (a link to the Windows disk,
    # or a download), so it is writable by all; the sticky bit keeps the
    # engine, root's, from being removed by them.
    chmod 1777 "$ROOT/opt/nemo/artist"
fi

if [ "$PS1" -eq 1 ]; then
    # The PlayStation (owner, 2026-11-06: "add playstation also"). Debian
    # packages no PS1 core, so PCSX ReARMed is built here from a pinned tag
    # by build-pcsx.sh, into the folder Debian's retroarch keeps its cores
    # in, where nemo/gaming.py looks. No BIOS: the core's own stands in.
    say "the PlayStation's core: PCSX ReARMed, pinned"
    in_root env NEMO_BUILD_DIR=/var/tmp/nemo-pcsx /opt/nemo/app/build-pcsx.sh
    test -f "$ROOT/usr/lib/x86_64-linux-gnu/libretro/pcsx_rearmed_libretro.so"
fi

say "the list nemodoc compares Nemo's files with (not signed: see nemodoc)"
in_root sh -c "cd /opt/nemo/app && find . -type f ! -name '*.pyc' ! -path '*/__pycache__/*' \
    | LC_ALL=C sort | xargs -d '\n' sha256sum > /opt/nemo/manifest.sha256"
wc -l < "$ROOT/opt/nemo/manifest.sha256"

say "tidied"
in_root apt-get clean
rm -rf "$ROOT/var/lib/apt/lists"/* "$ROOT/usr/sbin/policy-rc.d" "$ROOT/etc/resolv.conf"
echo nemo > "$ROOT/etc/hostname"
# live-boot writes a file here early in a boot and says so on the screen
# if the folder is not there, which without ifupdown it is not.
mkdir -p "$ROOT/etc/network"
if [ "$WSL1" -eq 1 ]; then
    rm -f "$ROOT/usr/bin/systemd-sysusers"
    in_root dpkg-divert --local --rename --remove /usr/bin/systemd-sysusers
    [ -x "$ROOT/usr/bin/systemd-sysusers" ] || { echo "the real systemd-sysusers did not come back" >&2; exit 1; }
    file "$ROOT/usr/bin/systemd-sysusers" 2>/dev/null | grep -q ELF || \
        head -c 4 "$ROOT/usr/bin/systemd-sysusers" | grep -q ELF || \
        { echo "systemd-sysusers in the image is not the real program" >&2; exit 1; }
fi
KERNEL="$(ls "$ROOT"/boot/vmlinuz-* | sort | tail -1)"
INITRD="$(ls "$ROOT"/boot/initrd.img-* | sort | tail -1)"
cp "$KERNEL" "$ISO/live/vmlinuz"
cp "$INITRD" "$ISO/live/initrd.img"
unmount

say "the file system, packed"
mksquashfs "$ROOT" "$ISO/live/filesystem.squashfs" -comp xz -noappend -no-progress \
    -e "$ROOT/proc" -e "$ROOT/sys" -e "$ROOT/dev/pts" > "$WORK/mksquashfs.log"
tail -3 "$WORK/mksquashfs.log"
# The tree is in the squashfs now, and the kernel and initrd are copied
# out. Removed here so the disk holds the tree and the image one at a
# time: on the machine this was written on there was room for little more.
rm -rf "$ROOT"

say "boot loaders: BIOS (isolinux) and UEFI (grub)"
LIVE="boot=live components hostname=nemo username=nemo"
cp /usr/lib/ISOLINUX/isolinux.bin "$ISO/isolinux/"
for m in ldlinux.c32 libcom32.c32 libutil.c32 menu.c32; do
    cp "/usr/lib/syslinux/modules/bios/$m" "$ISO/isolinux/"
done
cat > "$ISO/isolinux/isolinux.cfg" <<EOF
UI menu.c32
PROMPT 0
TIMEOUT 50
MENU TITLE NemoIso
DEFAULT nemo
LABEL nemo
  MENU LABEL Nemo (live)
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img $LIVE quiet
LABEL persist
  MENU LABEL Nemo (live, keeping changes on the stick)
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img $LIVE persistence quiet
LABEL serial
  MENU LABEL Nemo (live, messages on the serial port)
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img $LIVE console=tty0 console=ttyS0,115200
EOF
cat > "$WORK/grub.cfg" <<EOF
search --no-floppy --set=root --file /live/vmlinuz
set timeout=5
menuentry "Nemo (live)" {
    linux /live/vmlinuz $LIVE quiet
    initrd /live/initrd.img
}
menuentry "Nemo (live, keeping changes on the stick)" {
    linux /live/vmlinuz $LIVE persistence quiet
    initrd /live/initrd.img
}
menuentry "Nemo (live, messages on the serial port)" {
    linux /live/vmlinuz $LIVE console=tty0 console=ttyS0,115200
    initrd /live/initrd.img
}
EOF
cp "$WORK/grub.cfg" "$ISO/boot/grub/grub.cfg"
grub-mkstandalone -O x86_64-efi -o "$WORK/BOOTX64.EFI" \
    --modules="part_gpt part_msdos fat iso9660 search normal linux all_video" \
    "boot/grub/grub.cfg=$WORK/grub.cfg"
cp "$WORK/BOOTX64.EFI" "$ISO/EFI/BOOT/BOOTX64.EFI"
# The EFI system partition as an image, made without a loop device, and
# sized from what goes in it: a fixed 8 MB was too small for grub's image
# and the first build stopped here with "Disk full".
EFI_MB=$(( $(stat -c %s "$WORK/BOOTX64.EFI") / 1048576 + 4 ))
dd if=/dev/zero of="$ISO/EFI/efiboot.img" bs=1M count="$EFI_MB" status=none
mkfs.vfat "$ISO/EFI/efiboot.img" >/dev/null
mmd -i "$ISO/EFI/efiboot.img" ::/EFI ::/EFI/BOOT
mcopy -i "$ISO/EFI/efiboot.img" "$WORK/BOOTX64.EFI" ::/EFI/BOOT/BOOTX64.EFI

say "the image"
xorriso -as mkisofs -iso-level 3 -full-iso9660-filenames -volid NEMOISO \
    -eltorito-boot isolinux/isolinux.bin -eltorito-catalog isolinux/boot.cat \
    -no-emul-boot -boot-load-size 4 -boot-info-table \
    -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin \
    -eltorito-alt-boot -e EFI/efiboot.img -no-emul-boot -isohybrid-gpt-basdat \
    -output "$OUT" "$ISO" 2> "$WORK/xorriso.log" || { tail -20 "$WORK/xorriso.log"; exit 1; }
ls -la "$OUT"
sha256sum "$OUT"
echo "Written: $OUT"
