#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE='labpasid/jupiter-analytics'
CONTAINER='jupiter-mono'
KEEP_ALIVE=0
SELECT_VERSION=0
TARGET_VERSION=''
while [[ $# -gt 0 ]]; do
    case "$1" in
        --keep-alive|--no-kill) KEEP_ALIVE=1; shift ;;
        --select-version) SELECT_VERSION=1; shift ;;
        --version) TARGET_VERSION="$2"; shift 2 ;;
        --version=*) TARGET_VERSION="${1#*=}"; shift ;;
        *) printf '[ERROR] Unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done

step() {
    local number=$1 label=$2 filled i
    filled=$(( (number-1)*6/5 ))
    printf '\n['
    for ((i=0; i<6; i++)); do
        if ((i<filled)); then printf '#'; else printf '.'; fi
    done
    printf '] %d/5 %s\n' "$number" "$label"
}
fail() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }
cleanup() { [[ -z ${TMP_INSTALLER:-} ]] || rm -f "$TMP_INSTALLER"; }
trap cleanup EXIT

docker_cmd() { "${DOCKER_CMD[@]}" "$@"; }
port_free() {
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$1" <<'PY'
import socket, sys
s = socket.socket()
try:
    s.bind(('127.0.0.1', int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
    elif command -v lsof >/dev/null 2>&1; then
        ! lsof -nP -iTCP:"$1" -sTCP:LISTEN -t | grep -q .
    elif command -v ss >/dev/null 2>&1; then
        ! ss -ltn "sport = :$1" | tail -n +2 | grep -q .
    else
        fail 'Install python3, lsof, or ss to check port availability.'
    fi
}
wait_port_free() {
    local port=$1 seconds=${2:-15} i
    for ((i=0; i<seconds*2; i++)); do
        if port_free "$port"; then return 0; fi
        sleep 0.5
    done
    port_free "$port"
}
wait_tick() {
    local elapsed=$1 limit=$2 label=$3 marker j
    marker=$(( (elapsed / 3) % 6 ))
    printf '\r[ '
    for ((j=0; j<6; j++)); do
        if ((j==marker)); then printf '#'; else printf '.'; fi
    done
    printf ' ] %s - %ds elapsed (limit %ds)   ' "$label" "$elapsed" "$limit"
}
wait_docker() {
    local i successes=0
    for ((i=0; i<120; i++)); do
        if docker_cmd info >/dev/null 2>&1 && docker_cmd ps >/dev/null 2>&1; then
            successes=$((successes+1))
            if ((successes >= 3)); then printf '\n'; return 0; fi
        else
            successes=0
        fi
        wait_tick "$((i*3))" 360 'Waiting for Docker'
        sleep 3
    done
    printf '\n'
    return 1
}
pull_image() {
    local reference=$1 attempt
    for ((attempt=1; attempt<=5; attempt++)); do
        wait_docker || fail 'Docker did not become ready within 6 minutes. Check the application, permissions, and virtualization.'
        printf 'Pulling %s (attempt %d of 5)...\n' "$reference" "$attempt"
        if docker_cmd pull "$reference"; then return 0; fi
        if ((attempt < 5)); then
            printf 'Download failed. Waiting 15 seconds before retrying.\n' >&2
            sleep 15
        fi
    done
    fail "Could not pull $reference after 5 attempts. Check your network connection and the Docker messages above."
}
wait_http() {
    local url=$1 limit=$2 label=$3 i
    for ((i=0; i<limit; i+=3)); do
        if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then printf '\n'; return 0; fi
        wait_tick "$i" "$limit" "$label"
        sleep 3
    done
    printf '\n'
    return 1
}
open_jupiter() {
    local url=$1
    printf 'Opening Jupiter Analytics in your browser...\n'
    if [[ $OS_NAME == Darwin ]]; then
        if open "$url" >/dev/null 2>&1; then return 0; fi
    else
        if command -v xdg-open >/dev/null 2>&1 && xdg-open "$url" >/dev/null 2>&1; then return 0; fi
        if command -v gio >/dev/null 2>&1 && gio open "$url" >/dev/null 2>&1; then return 0; fi
        if command -v sensible-browser >/dev/null 2>&1 && sensible-browser "$url" >/dev/null 2>&1; then return 0; fi
    fi
    printf '[WARNING] Could not open the browser automatically. Open manually: %s\n' "$url" >&2
}

printf '\n==============================================\n'
printf '       Jupiter Analytics | Setup\n'
printf '==============================================\n'
OS_NAME=$(uname -s)
[[ $OS_NAME == Linux || $OS_NAME == Darwin ]] || fail 'Unsupported operating system.'
step 1 'Checking Docker'
if ! command -v docker >/dev/null 2>&1; then
    if [[ $OS_NAME == Linux ]]; then
        command -v curl >/dev/null 2>&1 || fail 'curl is required to install Docker.'
        command -v sudo >/dev/null 2>&1 || fail 'sudo is required to install Docker.'
        printf 'Installing Docker Engine via the official installer. Administrator password will be requested.\n'
        TMP_INSTALLER=$(mktemp)
        curl -fL --retry 3 --progress-bar https://get.docker.com -o "$TMP_INSTALLER" || fail 'Failed to download Docker installer.'
        sudo sh "$TMP_INSTALLER" || fail 'Failed to install Docker.'
    else
        if [[ -d /Applications/Docker.app ]]; then
            printf "Docker Desktop is already installed.\n"
        elif command -v brew >/dev/null 2>&1; then
            brew install --cask docker || fail 'Failed to install Docker Desktop.'
        else
            command -v curl >/dev/null 2>&1 || fail 'curl is required to install Docker Desktop.'
            tmpbase=$(mktemp -t jupiter-docker)
            rm -f "$tmpbase"
            TMP_INSTALLER="$tmpbase.dmg"
            arch=$(uname -m)
            case "$arch" in
                arm64) docker_arch=arm64 ;;
                x86_64) docker_arch=amd64 ;;
                *) fail "Unsupported macOS architecture: $arch" ;;
            esac
            curl -fL --retry 3 --progress-bar "https://desktop.docker.com/mac/main/$docker_arch/Docker.dmg" -o "$TMP_INSTALLER" || fail 'Failed to download Docker Desktop.'
            hdiutil attach "$TMP_INSTALLER" -quiet || fail 'Could not mount the Docker Desktop installer.'
            sudo /Volumes/Docker/Docker.app/Contents/MacOS/install || { hdiutil detach /Volumes/Docker -quiet || true; fail 'Failed to install Docker Desktop.'; }
            hdiutil detach /Volumes/Docker -quiet || true
        fi
        export PATH="$HOME/.docker/bin:/usr/local/bin:$PATH"
    fi
fi
if [[ $OS_NAME == Darwin ]]; then
    export PATH="$HOME/.docker/bin:/usr/local/bin:$PATH"
    open -a Docker || fail 'Could not launch Docker Desktop.'
    for ((i=0; i<40; i++)); do
        command -v docker >/dev/null 2>&1 && break
        wait_tick "$((i*3))" 120 'Waiting for Docker CLI'
        sleep 3
    done
    printf '\n'
fi
command -v docker >/dev/null 2>&1 || fail 'Docker was installed, but the docker command was not found.'
DOCKER_CMD=(docker)
command -v curl >/dev/null 2>&1 || fail 'curl is required to verify the application.'
step 2 'Starting Docker'
if [[ $OS_NAME == Linux ]]; then
    if ! docker info >/dev/null 2>&1; then
        if command -v systemctl >/dev/null 2>&1; then
            sudo systemctl enable --now docker || fail 'Could not start the Docker service.'
        else
            sudo service docker start || fail 'Could not start the Docker service.'
        fi
        if ! docker info >/dev/null 2>&1; then
            sudo -v || fail 'Permission denied when accessing Docker.'
            DOCKER_CMD=(sudo docker)
            printf 'Using temporary sudo access for this session.\n'
        fi
    fi
fi
wait_docker || fail 'Docker did not become ready within 6 minutes. Check the application, permissions, and virtualization.'
[[ $(docker_cmd info --format '{{.OSType}}') == linux ]] || fail 'Configure Docker to use Linux containers.'
step 3 'Selecting and pulling the image'
VERSION=latest
if [[ -n "$TARGET_VERSION" ]]; then
    VERSION="$TARGET_VERSION"
    printf 'Using specified version: %s\n' "$VERSION"
elif command -v python3 >/dev/null 2>&1; then
    tags=$(curl -fsS --max-time 30 "https://hub.docker.com/v2/repositories/$IMAGE/tags/?page_size=100" 2>/dev/null) || tags=''
    if [[ -n $tags ]]; then
        latest_numbered=$(python3 -c 'import sys,json,re; names=[x["name"] for x in json.load(sys.stdin).get("results",[])]; nums=[x for x in names if re.fullmatch(r"v?[0-9]+\.[0-9]+\.[0-9]+",x)]; print(max(nums,key=lambda x: tuple(map(int,x.lstrip("v").split("."))),default="latest"))' <<< "$tags") || latest_numbered=latest
        VERSION=$latest_numbered
    fi
fi
if ((SELECT_VERSION)); then
    printf 'Available versions:\n'
    if [[ -n ${tags:-} ]] && command -v python3 >/dev/null 2>&1; then
        python3 -c 'import sys,json; [print("  " + x["name"]) for x in json.load(sys.stdin).get("results",[])[:20]]' <<< "$tags" || true
    fi
    read -r -p "Desired version (Press Enter for $VERSION): " selected
    VERSION=${selected:-$VERSION}
fi
[[ $VERSION =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || fail 'Invalid Docker version.'
printf 'Docker will show the download progress for each image layer below.\n'
pull_image "$IMAGE:$VERSION"
step 4 'Configuring storage and network ports'
DATA_DIR="$HOME/Documents/JupiterModels"
mkdir -p "$DATA_DIR" || fail 'Could not create the models directory.'
if docker_cmd container inspect "$CONTAINER" >/dev/null 2>&1; then
    docker_cmd rm -f "$CONTAINER" >/dev/null || fail 'Could not replace the previous container.'
    wait_port_free 3001 15 || fail 'Port 3001 is still in use after stopping the previous container.'
    wait_port_free 8080 15 || fail 'Port 8080 is still in use after stopping the previous container.'
    wait_port_free 80 5 || true
else
    port_free 3001 || fail 'Port 3001 is already in use. Free it for the backend API.'
    port_free 8080 || fail 'Port 8080 is already in use. Free it for the stochastic engine.'
fi
FRONT_PORT=80
while ! port_free "$FRONT_PORT"; do
    FRONT_PORT=$((FRONT_PORT+1))
    ((FRONT_PORT <= 65535)) || fail 'No free port available for the frontend.'
done
step 5 'Starting and verifying the application'
docker_cmd run -d --restart unless-stopped --name "$CONTAINER" \
    -p "127.0.0.1:$FRONT_PORT:80" \
    -p '127.0.0.1:3001:3001' \
    -p '127.0.0.1:8080:8080' \
    -v "$DATA_DIR:/app/data" "$IMAGE:$VERSION" >/dev/null || fail 'Failed to start the container.'
URL="http://localhost:$FRONT_PORT"
if ! wait_http "$URL/" 180 'Verifying frontend' || ! wait_http 'http://localhost:3001/health' 30 'Verifying API'; then
    docker_cmd logs --tail 60 "$CONTAINER" >&2 || true
    fail 'The container started, but the application did not respond in time.'
fi
printf '\n[######] 5/5 Ready! Application: %s\n' "$URL"
printf 'Models saved in: %s\n' "$DATA_DIR"
open_jupiter "$URL"
if (( ! KEEP_ALIVE )); then printf 'The container will continue running in the background. To stop it: docker stop %s\n' "$CONTAINER"; fi
