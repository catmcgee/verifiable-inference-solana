# report/ — HTML report generator

Turns harness JSONL into a single self-contained HTML report
(`report/out/report.html`): inline CSS, hand-rolled inline SVG charts, no CDN,
no JS frameworks. Light and dark theme, table view under every chart, and a
data-provenance footer (run_id range + count) on every chart.

## Regenerate

From the repo root:

```sh
make report

# open it
open report/out/report.html
```

`make report` first runs `report/curate_runs.py`, which validates the complete
raw SNP twin and Leg C files, rejects duplicate run IDs, and atomically rebuilds
`runs/real-requests.jsonl`. It then regenerates both
`report/measurements.json`/`web/public/measurements.json` and the HTML report.

To render a separate already-curated harness output instead:

```sh
uv run report/generate.py \
  --requests runs/2026-08-01/requests.jsonl \
  --sessions runs/2026-08-01/sessions.jsonl \
  --out report/out/report.html
```

## Parameters

| Flag | Default | Meaning |
|---|---|---|
| `--requests` | `runs/real-requests.jsonl` | real per-request JSONL (validates against `harness/schema.json`) |
| `--sessions` | `runs/all-sessions.jsonl` | real per-session JSONL (validates against `harness/session_schema.json`) |
| `--out` | `report/out/report.html` | output path |
| `--box-cost-per-hr` | `2.50` | box amortization $/hour — drives every $/1M-token number; the value used is stated in the report |
| `--api-input-per-mtok` | `1.00` | published Haiku 4.5 API input price for leg C rows |
| `--api-output-per-mtok` | `5.00` | published Haiku 4.5 API output price for leg C rows |

## Validate inputs against the frozen schemas

```sh
uv run --with jsonschema --with rfc3339-validator - <<'EOF'
import json
from jsonschema import Draft202012Validator, FormatChecker
for jf, sf in [("runs/real-requests.jsonl", "harness/schema.json"),
               ("runs/all-sessions.jsonl", "harness/session_schema.json")]:
    v = Draft202012Validator(json.load(open(sf)), format_checker=FormatChecker())
    recs = [json.loads(l) for l in open(jf)]
    errs = sum(1 for r in recs for _ in v.iter_errors(r))
    print(f"{jf}: {len(recs)} records, {errs} errors")
EOF
```

## Notes

- Aggregation: median throughout, p99 where tails matter. A/B/C cells target
  n ≥ 10; Leg D targets n = 5. The generator groups by the frozen cell
  dimensions and excludes the earliest 2 from aggregation while leaving raw
  JSONL unchanged for auditability.
- Leg D has no `rung_id` in the frozen v1 request schema, so the rung is
  encoded in the model field (`bitnet-2b-rung1` … `rung3`). A schema change
  would migrate old JSONL, never fork it.
- Chart palette and mark specs follow the validated reference dataviz palette
  (fixed categorical slot order; SEV-off is always slot 1 blue, SEV-on slot 2
  green across the whole report).
