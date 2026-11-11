#!/bin/sh
# Download the language models Nemo's modes use, into ~/.nemo/models.
#
# Rewritten on 2026-10-08 with the rest of the NemoIso files. The list is
# the one in nemo/offline.py (MODEL_SOURCES), and a test holds the two
# together.
#
#   fetch-models.sh              the four everyday models, about 6.5 GB
#   fetch-models.sh qwen3-1.7b   only the ones named
#   fetch-models.sh --all        those and Deep mode's 8B model as well
#   fetch-models.sh artist       only the Artist's image model and decoder
#   fetch-models.sh --no-artist  the everyday models without the Artist's
#
# Nothing is fetched unless this is run: the ISO carries no model.
#
# The Artist's files (story covers, 2 GB) go to /opt/nemo/artist, where
# nemo/artist.py looks and the image's sd-cli is, and are hash-checked
# before they are put there. On a live boot that folder, like the home, is
# in RAM unless the stick's persistence is on: 2 GB of the AH531's 8, and
# painting needs 2.9 GB more free. So it is fetched only where there is
# room for it and 512 MB to spare, and nemodoc first links the copy on the
# Windows disk (C:\Nemo\artist), which costs no RAM.
set -eu

DEST="${NEMO_HOME:-$HOME/.nemo}/models"
BASE="https://huggingface.co"
ARTIST_DEST="${NEMO_ARTIST:-/opt/nemo/artist}"

# file|url|sha256|bytes -- nemo/artist.py's SOURCES, and the same files
# NemoDoc.ps1 fetches on Windows; a test holds the three together
ARTIST="$(cat <<'EOF'
"sd_turbo-f16-q8_0.gguf|https://huggingface.co/Green-Sky/SD-Turbo-GGUF/resolve/main/sd_turbo-f16-q8_0.gguf|d50be7655f0a554cf8041c145d88b210bd5f3c545423119dee62ae08cae51580|2023745376"
"taesd.safetensors|https://huggingface.co/madebyollin/taesd/resolve/main/diffusion_pytorch_model.safetensors|db169d69145ec4ff064e49d99c95fa05d3eb04ee453de35824a6d0f325513549|9793292"
EOF
)"

# name|repository|file
MODELS="$(cat <<'EOF'
"gemma3-1b|unsloth/gemma-3-1b-it-GGUF|gemma-3-1b-it-Q4_K_M.gguf"
"qwen3-1.7b|unsloth/Qwen3-1.7B-GGUF|Qwen3-1.7B-Q4_K_M.gguf"
"qwen2.5-coder-3b|Qwen/Qwen2.5-Coder-3B-Instruct-GGUF|qwen2.5-coder-3b-instruct-q4_k_m.gguf"
"qwen3-4b|Qwen/Qwen3-4B-GGUF|Qwen3-4B-Q4_K_M.gguf"
"qwen3-8b|Qwen/Qwen3-8B-GGUF|Qwen3-8B-Q4_K_M.gguf"
EOF
)"

want=""
all=0
artist=1
for arg in "$@"; do
    case "$arg" in
        --all) all=1 ;;
        --no-artist) artist=0 ;;
        -*) echo "unknown option $arg" >&2; exit 2 ;;
        *) want="$want $arg" ;;
    esac
done
case " $want " in
    *" artist "*) ;;
    "  ") ;;
    *) artist=0 ;;                                 # names given, artist not one
esac

fetch_artist() {        # 0 if all there; prints what it did
    rc=0
    mkdir -p "$ARTIST_DEST" || { echo "FAILED artist: cannot write $ARTIST_DEST" >&2; return 1; }
    while IFS='|' read -r file url sha bytes; do
        [ -n "$file" ] || continue
        out="$ARTIST_DEST/$file"
        if [ -s "$out" ] && [ "$(wc -c < "$out" | tr -d ' ')" = "$bytes" ]; then
            echo "have   artist $file"
            continue
        fi
        part="$out.unchecked"
        have=0
        [ -f "$part" ] && have="$(wc -c < "$part" | tr -d ' ')"
        free_kb="$(df -Pk "$ARTIST_DEST" | awk 'NR==2 {print $4}')"
        need_kb=$(( (bytes - have) / 1024 + 524288 ))
        if [ "${free_kb:-0}" -lt "$need_kb" ]; then
            echo "FAILED artist $file: $((free_kb / 1024)) MB free in $ARTIST_DEST and it needs" \
                 "$((need_kb / 1024)) MB. On a live boot that is RAM: boot with persistence," \
                 "or keep the files in C:\\Nemo\\artist on the Windows disk." >&2
            rc=1
            continue
        fi
        echo "fetch  artist $file"
        # Resumed if cut short; put where Nemo looks only once its hash is right.
        if [ "$have" != "$bytes" ] && ! curl -fL --retry 3 -C - -o "$part" "$url"; then
            echo "FAILED artist $file: $url" >&2
            rc=1
            continue
        fi
        if echo "$sha  $part" | sha256sum -c - >/dev/null 2>&1; then
            mv "$part" "$out"
        else
            rm -f "$part"
            echo "FAILED artist $file: it did not match the expected hash and was deleted" >&2
            rc=1
        fi
    done <<EOF
$(echo "$ARTIST" | tr -d '"')
EOF
    return "$rc"
}

if [ "$want" = " artist" ]; then              # only the Artist's
    fetch_artist
    exit $?
fi

mkdir -p "$DEST"
failed=0
# D195: fed from a here-document, not a pipe. A pipe ran the loop in a
# subshell, so failed=1 set inside it was lost and every run exited 0.
while IFS='|' read -r name repo file; do
    [ -n "$name" ] || continue
    if [ -n "$want" ]; then
        case " $want " in *" $name "*) ;; *) continue ;; esac
    elif [ "$all" -eq 0 ] && [ "$name" = "qwen3-8b" ]; then
        continue                                   # Deep mode only: ask for it
    fi
    out="$DEST/$name.gguf"
    if [ -s "$out" ]; then
        echo "have   $name"
        continue
    fi
    echo "fetch  $name  ($repo)"
    # To a .part file first: an interrupted download is not left looking whole.
    if curl -fL --retry 3 -C - -o "$out.part" "$BASE/$repo/resolve/main/$file"; then
        mv "$out.part" "$out"
    else
        echo "FAILED $name: $BASE/$repo/resolve/main/$file" >&2
        failed=1
    fi
done <<EOF
$(echo "$MODELS" | tr -d '"')
EOF
if [ "$artist" -eq 1 ]; then
    fetch_artist || failed=1
fi
exit "$failed"
