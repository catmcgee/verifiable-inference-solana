#!/usr/bin/env bash
set -e
pkill -f "uvicorn" 2>/dev/null || true
sleep 1
pgrep -f "llama-server" >/dev/null || {
  export LD_LIBRARY_PATH=/mnt/models/bitnet-bin
  nohup /mnt/models/bitnet-bin/llama-server -m /mnt/models/models/bitnet-b1.58-2B-4T-i2_s.gguf \
    --port 8601 --host 127.0.0.1 -t 28 -c 4096 --no-warmup > ~/bitnet.log 2>&1 &
}
cd ~/verified-inference
export PATH=$HOME/.local/bin:$PATH
VINFER_SEV_MODE=snp nohup uv run uvicorn server.main:app --host 0.0.0.0 --port 8477 > ~/vinfer.log 2>&1 &
sleep 6
curl -s -m 5 http://127.0.0.1:8477/v1/attestation > /tmp/att.json
python3 -c "import json; d=json.load(open(\"/tmp/att.json\")); print(\"grade:\", d[\"grade\"]); print(\"report:\", bool(d.get(\"snp_report_b64\"))); print(d[\"note\"][:90])"
