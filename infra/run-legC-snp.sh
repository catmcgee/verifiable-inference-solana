#!/usr/bin/env bash
# Run direct and proxied Claude calls from inside the SNP guest after Leg B is idle.
set -euo pipefail

cd "$HOME/verified-inference"
export PATH="$HOME/.local/bin:$PATH"
set -a
# Local-only API credential; this file is gitignored and is never printed.
source .env.local
set +a
: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY is required in .env.local}"
test -c /dev/sev-guest
if [ ! -r /dev/sev-guest ] || [ ! -w /dev/sev-guest ]; then
  sudo chgrp "$(id -gn)" /dev/sev-guest
  sudo chmod 0660 /dev/sev-guest
fi
test -r /dev/sev-guest -a -w /dev/sev-guest

export VINFER_PROXY_TOKEN
VINFER_PROXY_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
export VINFER_SEV_MODE=snp
export VINFER_C_PROXY_API=http://127.0.0.1:8480/v1/chat/completions
export VINFER_C_N="${VINFER_C_N:-8}"
export VINFER_REQUIRE_AUTH=1
export VINFER_AUTH_TOKEN="$VINFER_PROXY_TOKEN"

uv run uvicorn server.proxy.legc_proxy:app --host 127.0.0.1 --port 8480 \
  --no-access-log >/tmp/legC-proxy.log 2>&1 &
PROXY_PID=$!
trap 'kill "$PROXY_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  curl -sf http://127.0.0.1:8480/healthz >/dev/null && break
  sleep 1
done
curl -sf http://127.0.0.1:8480/healthz >/dev/null
curl -sf http://127.0.0.1:8480/v1/attestation >/tmp/legC-proxy-attestation.json
uv run python - <<'PY'
import json
from cli.attest_verify import verify_attestation

doc = json.load(open('/tmp/legC-proxy-attestation.json'))
verdict = verify_attestation(doc, require_hpke=False)
assert verdict.trusted, verdict.reason
print(f'Leg C proxy identity: grade={verdict.grade}; {verdict.reason}')
PY

uv run python -m server.proxy.legc_probe runs/legC-full.jsonl
uv run python - <<'PY'
import json
from pathlib import Path
rows = [json.loads(line) for line in Path('runs/legC-full.jsonl').read_text().splitlines()]
tokens_in = sum(row['prompt_tokens'] for row in rows)
tokens_out = sum(row['output_tokens'] for row in rows)
# Haiku 4.5 rates used for experiment budgeting; refresh before publication.
cost = tokens_in / 1_000_000 * 1.0 + tokens_out / 1_000_000 * 5.0
print(f'Leg C rows={len(rows)} tokens={tokens_in} in/{tokens_out} out estimated_cost=${cost:.4f}')
PY
