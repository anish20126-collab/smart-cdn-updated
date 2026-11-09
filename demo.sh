#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    printf '%s\n' 'Usage: ./demo.sh [--scenario all|normal|congestion|server-failure|link-failure|comparison|cli] [--trials N] [--present]' 'Default: all cases, one static + one dynamic batch each. Run as your normal user.'
    exit 0
fi
mkdir -p "$PWD/results"
output=$(mktemp -d "$PWD/results/$(date +%Y%m%d-%H%M%S)-XXXXXX")
mkdir -p "$output"
controller_pid=''
cleanup() {
    if [[ -n "$controller_pid" ]]; then
        kill "$controller_pid" 2>/dev/null || true
        wait "$controller_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
# Obtain permission before starting the experiment; sudo is limited to Mininet.
sudo -v
demo_started=$SECONDS
python3 -B generate_content.py
./sdn-env/bin/python -B sdn_launcher.py --results "$output" > "$output/controller.log" 2>&1 &
controller_pid=$!
sleep 1
if ! kill -0 "$controller_pid" 2>/dev/null; then cat "$output/controller.log"; exit 1; fi
status=0
sudo /usr/bin/python3 -B experiment.py --results "$output" "$@" || status=$?
python3 -B plot_results.py "$output" || status=1
printf 'Results: %s\n' "$output"
printf 'Elapsed demo time: %s seconds (including presentation pauses)\n' "$((SECONDS-demo_started))"
exit "$status"
