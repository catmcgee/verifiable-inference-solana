#!/usr/bin/env bash
# Registry-driven model runtime launcher. Run on the inference host/guest.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
THREADS=${1:-64}
cd "$ROOT"
exec uv run python -m server.launch --threads "$THREADS"
