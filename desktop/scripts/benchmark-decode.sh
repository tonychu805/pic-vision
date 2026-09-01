#!/usr/bin/env bash
# Real capacity test for N100-class (or any Intel Quick Sync) hardware
# running this project's desktop client: can it hold N cameras' worth of
# live-view decode, optionally alongside a proxy encode (ADR-069's 720p
# proxy, the one real point where two workloads overlap)?
#
# Written 2026-09-01 after the operator asked "would N100 hold for 4
# cameras" with no N100 in hand to test on -- this project's own dev
# workstation can't stand in (an HEDT Core i7-7820X with no integrated
# GPU at all; its only /dev/dri/renderD128 node belongs to the discrete
# NVIDIA card, PCI vendor 0x10de, not Intel 0x8086 -- confirmed by
# checking, not assumed, since a presence-only check on that device node
# would have silently passed on hardware that can't actually do this).
# Run this ON the real target box.
#
# Real numbers this project's own camera produced (measured 2026-09-01,
# BC510 sub-stream via ffprobe packet sampling): 1920x1080, ~13fps,
# ~744kbps H.264. Use your own camera's actual sub-stream URL -- resolution
# and bitrate both move the real answer.
#
# Usage:
#   ./benchmark-decode.sh <rtsp_url> [num_streams] [--with-proxy-encode]
#
# Example:
#   ./benchmark-decode.sh "rtsp://user:pass@192.168.1.121:554/2" 4 --with-proxy-encode

set -euo pipefail

URL="${1:?Usage: $0 <rtsp_url> [num_streams] [--with-proxy-encode]}"
N="${2:-4}"
WITH_ENCODE=false
[[ "${3:-}" == "--with-proxy-encode" ]] && WITH_ENCODE=true

echo "=== Checking for real Intel Quick Sync hardware (not just a render node) ==="
if ! ffmpeg -hide_banner -hwaccels 2>&1 | grep -q vaapi; then
  echo "ffmpeg has no VAAPI support built in on this machine -- can't run this test here."
  exit 1
fi

INTEL_DEVICE=""
for card in /sys/class/drm/render*; do
  [ -e "$card/device/vendor" ] || continue
  vendor=$(cat "$card/device/vendor")
  name=$(basename "$card")
  if [ "$vendor" = "0x8086" ]; then
    INTEL_DEVICE="/dev/dri/$name"
    echo "Found Intel GPU device: $INTEL_DEVICE"
    break
  fi
done

if [ -z "$INTEL_DEVICE" ]; then
  echo "No Intel GPU render node found (checked PCI vendor ID on every /dev/dri/render* device, not"
  echo "just whether one exists -- a non-Intel card can also expose a render node)."
  echo "This test needs to run ON the actual N100 (or other Quick-Sync) box, not here."
  exit 1
fi

echo ""
echo "=== Starting $N concurrent decode sessions from: $URL ==="
PIDS=()
LOGDIR=$(mktemp -d)
for i in $(seq 1 "$N"); do
  ffmpeg -hide_banner -loglevel warning -hwaccel vaapi -hwaccel_device "$INTEL_DEVICE" \
    -rtsp_transport tcp -i "$URL" -f null - > "$LOGDIR/decode_$i.log" 2>&1 &
  PIDS+=($!)
done

if $WITH_ENCODE; then
  echo "Also running a simultaneous 720p proxy encode (ADR-069) -- the real overlap case worth testing."
  ffmpeg -hide_banner -loglevel warning -hwaccel vaapi -hwaccel_device "$INTEL_DEVICE" \
    -rtsp_transport tcp -i "$URL" -vf 'scale_vaapi=w=1280:h=720' -c:v h264_vaapi -b:v 2M \
    -f null - > "$LOGDIR/proxy_encode.log" 2>&1 &
  PIDS+=($!)
fi

echo ""
echo "Running for 30s. In another terminal: 'top' for CPU, 'intel_gpu_top' (if installed) for the media engine."
sleep 30

echo "Stopping..."
for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
wait 2>/dev/null || true

echo ""
echo "=== Results ==="
for i in $(seq 1 "$N"); do
  speed=$(grep -oE 'speed=[0-9.]+x' "$LOGDIR/decode_$i.log" | tail -1)
  echo "Decode stream $i: last reported speed=${speed:-unknown}  (1.00x = keeping up in real time; below 1.00x = falling behind)"
done
if $WITH_ENCODE; then
  speed=$(grep -oE 'speed=[0-9.]+x' "$LOGDIR/proxy_encode.log" | tail -1)
  echo "Proxy encode:    last reported speed=${speed:-unknown}"
fi
echo ""
echo "Pass/fail: every line above needs speed >= 1.00x. If any stream falls behind, this box can't"
echo "hold $N cameras at this workload -- try fewer cameras, a lower sub-stream resolution, or without"
echo "--with-proxy-encode running at the same time (stagger it instead)."
echo ""
echo "Full logs kept at: $LOGDIR"
