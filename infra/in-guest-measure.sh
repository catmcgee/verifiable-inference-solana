#!/usr/bin/env bash
# Runs INSIDE a measurement VM (leg A plain-VM or leg B SEV-ES CVM). Same script
# both sides — the ONLY difference between runs is the VM's SEV state, which the
# caller passes as SEV_MODE so the JSONL records it (fair-comparison rule).
#
# Copied in + invoked over ssh by infra/run-legAB.sh. Produces:
#   ~/stream.txt     (STREAM triad — the memory-encryption tax anchor)
#   ~/ab.jsonl       (schema-valid inference rows, leg + sev_mode tagged)
set -uo pipefail
SEV_MODE="${SEV_MODE:-off}"     # off (leg A) | es (leg B)
LEG="${LEG:-A}"
THREADS="${THREADS:-$(nproc)}"

sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  build-essential curl >/dev/null 2>&1

# ---- STREAM triad (the anchor number, both SEV states) ----
if [ ! -x /tmp/stream_c ]; then
  curl -fsSL -o /tmp/stream.c https://raw.githubusercontent.com/jeffhammond/STREAM/master/stream.c
  # array sized to dwarf LLC so we hit DRAM; scale with guest RAM
  gcc -O3 -fopenmp -DSTREAM_ARRAY_SIZE=200000000 -DNTIMES=10 -mcmodel=large \
    /tmp/stream.c -o /tmp/stream_c
fi
OMP_NUM_THREADS="$THREADS" /tmp/stream_c | tee ~/stream.txt

# ---- inference (bitnet + 8b-q4) via the prebuilt llama.cpp copied to the guest ----
# The caller stages ~/llama-server, ~/models/*, and starts them; here we just
# drive them and emit schema rows. If servers aren't up, skip inference.
python3 - "$SEV_MODE" "$LEG" "$THREADS" <<'PY' || true
import json, sys, time, urllib.request, os
sev, leg, threads = sys.argv[1], sys.argv[2], int(sys.argv[3])
from datetime import datetime, timezone
ports = {"bitnet-2b": 8601, "8b-q4": 8602}
out = open(os.path.expanduser("~/ab.jsonl"), "w")
def infer(port, prompt, n):
    body = json.dumps({"prompt": prompt, "n_predict": n, "stream": True,
                       "cache_prompt": False}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/completion", body,
                                 {"content-type": "application/json"})
    t0 = time.perf_counter(); times=[];
    with urllib.request.urlopen(req, timeout=600) as r:
        for line in r:
            line=line.decode().strip()
            if line.startswith("data: "):
                d=json.loads(line[6:])
                if d.get("content"): times.append(time.perf_counter())
    return t0, times
for model, port in ports.items():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5)
    except Exception:
        continue
    for i in range(10):
        t0, times = infer(port, "measure "*32, 128)
        if len(times) < 2: continue
        itls = sorted((times[k]-times[k-1])*1000 for k in range(1,len(times)))
        rec = {"run_id": f"{leg}{sev}-{model}-{i}", "leg": leg, "model": model,
               "quant": "i2_s" if model=="bitnet-2b" else "Q4_K_M",
               "sev_mode": sev, "input_mode": "tls", "threads": threads,
               "numa_policy": "vm", "prompt_tokens": 32, "output_tokens": len(times),
               "batch": 1, "concurrency": 1,
               "ttft_ms": round((times[0]-t0)*1000,3),
               "itl_ms_p50": round(itls[len(itls)//2],3),
               "itl_ms_p99": round(itls[min(len(itls)-1,int(len(itls)*0.99))],3),
               "tokens_per_s": round((len(times)-1)/((times[-1]-times[0]) or 1),3),
               "e2e_ms": round((times[-1]-t0)*1000,3),
               "attest_fetch_ms":0,"attest_verify_ms":0,"receipt_sign_ms":0,
               "receipt_post_ms":0,"receipt_confirm_ms":0,"solana_cu":0,
               "solana_fee_lamports":0,
               "ts": datetime.now(timezone.utc).isoformat()}
        out.write(json.dumps(rec, sort_keys=True)+"\n")
out.close()
print("wrote ~/ab.jsonl")
PY
echo "in-guest measure done (SEV_MODE=$SEV_MODE LEG=$LEG)"
