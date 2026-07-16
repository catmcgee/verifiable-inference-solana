# report/ — HTML report generator

Turns harness JSONL into a single self-contained HTML report
(`report/out/report.html`): inline CSS, hand-rolled inline SVG charts, no CDN,
no JS frameworks. Light and dark theme, table view under every chart, and a
data-provenance footer (run_id range + count) on every chart per the standing
rule in PLAN.md.

## Regenerate

From the repo root (stdlib only — no dependencies):

```sh
# 1. (Re)build the synthetic fixtures — deterministic, seeded, fixed base timestamp
uv run harness/fixtures/gen_synthetic.py

# 2. Render the report from the fixtures (the defaults)
uv run report/generate.py

# open it
open report/out/report.html
```

Point it at real harness output instead:

```sh
uv run report/generate.py \
  --requests runs/2026-08-01/requests.jsonl \
  --sessions runs/2026-08-01/sessions.jsonl \
  --out report/out/report.html
```

## Parameters

| Flag | Default | Meaning |
|---|---|---|
| `--requests` | `harness/fixtures/synthetic.jsonl` | per-request JSONL (validates against `harness/schema.json`) |
| `--sessions` | `harness/fixtures/synthetic_sessions.jsonl` | per-session JSONL (validates against `harness/session_schema.json`) |
| `--out` | `report/out/report.html` | output path |
| `--box-cost-per-hr` | `2.50` | box amortization $/hour — drives every $/1M-token number; the value used is stated in the report |
| `--api-input-per-mtok` | `3.00` | published API input price for leg C rows |
| `--api-output-per-mtok` | `15.00` | published API output price for leg C rows |

## Validate fixtures against the frozen schemas

```sh
uv run --with jsonschema --with rfc3339-validator - <<'EOF'
import json
from jsonschema import Draft202012Validator, FormatChecker
for jf, sf in [("harness/fixtures/synthetic.jsonl", "harness/schema.json"),
               ("harness/fixtures/synthetic_sessions.jsonl", "harness/session_schema.json")]:
    v = Draft202012Validator(json.load(open(sf)), format_checker=FormatChecker())
    recs = [json.loads(l) for l in open(jf)]
    errs = sum(1 for r in recs for _ in v.iter_errors(r))
    print(f"{jf}: {len(recs)} records, {errs} errors")
EOF
```

## Notes

- If the requests path contains `synthetic`, the report renders a prominent
  "synthetic fixture data" banner. Every number from the fixtures is a modeled
  placeholder, not a measurement.
- Aggregation: median throughout, p99 where tails matter. The harness
  convention (n ≥ 5 per cell, first 2 discarded as warmup) is noted in the
  report's method section; fixture run_ids start at `s03` to reflect it.
- Leg D has no `rung_id` in the frozen v1 request schema, so the rung is
  encoded in the model field (`bitnet-2b-rung1` … `rung3`). A schema change
  would migrate old JSONL, never fork it.
- Chart palette and mark specs follow the validated reference dataviz palette
  (fixed categorical slot order; SEV-off is always slot 1 blue, SEV-on slot 2
  green across the whole report).
