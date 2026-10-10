#!/bin/sh
set -eu

# The base image starts headed Chromium through Xvfb. Recreate that setup while
# keeping the browser process out of root; stale Xvfb locks can survive restarts.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
export DISPLAY=:99
# CloakBrowser images may include a window manager in future releases; start it
# when present, while keeping minimal images valid.
if command -v openbox >/dev/null 2>&1; then
    openbox --sm-disable >/tmp/openbox.log 2>&1 &
fi
ready=0
for _ in $(seq 1 50); do
    if [ -S /tmp/.X11-unix/X99 ]; then
        ready=1
        break
    fi
    sleep 0.1
done
if [ "$ready" -ne 1 ]; then
    echo "Xvfb did not become ready" >&2
    exit 1
fi

# The profile is a host-path mount and may still be owned by the old root
# process. Fail closed if this service-owned migration cannot be completed.
PROFILE_DIR=${ASTRA_PROFILE_DIR:-/profile}
if ! mkdir -p "$PROFILE_DIR" || ! chown -R astra:astra "$PROFILE_DIR"; then
    echo "Could not transfer Astra browser profile ownership" >&2
    exit 1
fi
mkdir -p /home/astra/.cache
chown -R astra:astra /home/astra
export HOME=/home/astra
export XDG_CACHE_HOME=/home/astra/.cache
exec setpriv --reuid=astra --regid=astra --init-groups "$@"
