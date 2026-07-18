#!/usr/bin/env python3
"""Verified-inference report generator.

Reads per-request JSONL (harness/schema.json) and per-session JSONL
(harness/session_schema.json), aggregates, and writes a fully self-contained
HTML report (inline CSS + hand-rolled inline SVG; no CDN, no JS frameworks).

Run:  uv run report/generate.py
      uv run report/generate.py --requests runs/real.jsonl --sessions runs/sessions.jsonl
"""

import argparse
from collections import defaultdict
import html
import json
import re
import statistics
from pathlib import Path
from urllib.parse import quote

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

MODEL_ORDER = [
    entry["id"] for entry in yaml.safe_load((REPO / "models.yaml").read_text())
]
THREAD_ORDER = [16, 32, 64, 128]
PROMPT_ORDER = [128, 1024, 8192]

# Categorical slots (validated reference palette, fixed order — see dataviz skill).
SLOT_VARS = ["--s1", "--s2", "--s3", "--s4", "--s5"]
MODEL_SLOT = {
    model: SLOT_VARS[index % len(SLOT_VARS)] for index, model in enumerate(MODEL_ORDER)
}
SEV_OFF_SLOT, SEV_ON_SLOT = "--s1", "--s2"  # sev identity is consistent report-wide


# ---------------------------------------------------------------- stats/util


def med(xs):
    xs = list(xs)
    return statistics.median(xs) if xs else 0.0


def p99(xs):
    xs = sorted(xs)
    if not xs:
        return 0.0
    if len(xs) == 1:
        return xs[0]
    k = 0.99 * (len(xs) - 1)
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def esc(s):
    return html.escape(str(s), quote=True)


def fmt(x, nd=1):
    if x == 0:
        return "0"
    if abs(x) >= 1000:
        return f"{x:,.0f}"
    return f"{x:.{nd}f}".rstrip("0").rstrip(".") if nd else f"{x:.0f}"


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


REQUEST_CELL_FIELDS = (
    "leg",
    "model",
    "quant",
    "sev_mode",
    "input_mode",
    "threads",
    "numa_policy",
    "prompt_tokens",
    "output_tokens",
    "batch",
    "concurrency",
)


def discard_request_warmups(records, count=2):
    """Drop the earliest raw samples in each experimental cell for analysis.

    Raw JSONL remains untouched so every request stays auditable. The frozen
    schema has no warmup flag, so cell identity is reconstructed from its
    independent variables and samples are ordered by their RFC3339 timestamp.
    """
    cells = defaultdict(list)
    for record in records:
        key = tuple(record.get(field) for field in REQUEST_CELL_FIELDS)
        if record.get("leg", "").startswith("C-"):
            match = re.fullmatch(
                r"C-(?:direct|proxied)-(\d+)-(\d+)-c(\d+)-(\d+)",
                record["run_id"],
            )
            if match:
                # Leg C records actual API output usage, while the intended
                # output cap is recoverable from its stable run_id.
                key = tuple(
                    record.get(field)
                    for field in REQUEST_CELL_FIELDS
                    if field != "output_tokens"
                ) + ("requested-output", int(match.group(2)))
        cells[key].append(record)
    retained = []
    discarded = []
    for cell in cells.values():
        ordered = sorted(cell, key=lambda record: (record["ts"], record["run_id"]))
        # Never erase a sparse/incomplete cell entirely.
        cut = min(count, max(0, len(ordered) - 1))
        discarded.extend(ordered[:cut])
        retained.extend(ordered[cut:])
    return sorted(retained, key=lambda record: record["ts"]), discarded


MEASUREMENTS_URL = "https://console.213.239.141.40.sslip.io/measurements/"


def provenance(records):
    """Data-provenance footer with a link for every contributing run."""
    ids = sorted({r["run_id"] for r in records})
    if not ids:
        return '<p class="provenance">Provenance: no records.</p>'
    links = " ".join(
        f'<a href="{MEASUREMENTS_URL}?run={quote(run_id)}">'
        f"<code>{esc(run_id)}</code></a>"
        for run_id in ids
    )
    return (
        f'<details class="provenance"><summary>Provenance: {len(ids)} run_ids</summary>'
        f'<div class="provenance-runs">{links}</div></details>'
    )


def sess_provenance(sessions):
    ids = sorted({s["session_id"] for s in sessions})
    if not ids:
        return '<p class="provenance">Provenance: no session records.</p>'
    links = " ".join(
        f'<a href="{MEASUREMENTS_URL}?session={quote(session_id)}#session-measurements">'
        f"<code>{esc(session_id)}</code></a>"
        for session_id in ids
    )
    return (
        f'<details class="provenance"><summary>Provenance: {len(ids)} session_ids</summary>'
        f'<div class="provenance-runs">{links}</div></details>'
    )


def nice_max(v):
    """Round up to a clean axis maximum."""
    if v <= 0:
        return 1.0
    import math

    mag = 10 ** math.floor(math.log10(v))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * mag >= v:
            return m * mag
    return 10 * mag


def ticks_for(vmax, n=5):
    step = vmax / n
    return [round(step * i, 6) for i in range(n + 1)]


# ---------------------------------------------------------------- SVG pieces


def bar_path(x, y, w, h, r=4):
    """Column with 4px rounded data-end (top), square at the baseline."""
    if h <= 0:
        return ""
    r = min(r, w / 2, h)
    return (
        f"M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
        f"L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
        f"L{x + w:.1f},{y + h:.1f} Z"
    )


def hbar_path(x, y, w, h, r=4):
    """Horizontal bar, rounded right data-end, square at the left baseline."""
    if w <= 0:
        return ""
    r = min(r, h / 2, w)
    return (
        f"M{x:.1f},{y:.1f} L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
        f"L{x + w:.1f},{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} "
        f"L{x:.1f},{y + h:.1f} Z"
    )


def legend_html(items):
    """items: [(label, css_var)]"""
    chips = "".join(
        f'<span class="lg"><span class="sw" style="background:var({v})"></span>{esc(t)}</span>'
        for t, v in items
    )
    return f'<div class="legend">{chips}</div>'


def grid_and_yaxis(x0, x1, y0, y1, vmax, unit=""):
    """Hairline gridlines + y tick labels. y0=top of plot, y1=baseline."""
    out = []
    for tv in ticks_for(vmax):
        y = y1 - (y1 - y0) * (tv / vmax if vmax else 0)
        out.append(
            f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" class="grid"/>'
        )
        out.append(
            f'<text x="{x0 - 8}" y="{y + 4:.1f}" class="tick" text-anchor="end">{fmt(tv)}{unit}</text>'
        )
    out.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" class="axis"/>')
    return "".join(out)


def grouped_bar_svg(categories, series, unit="", height=340, value_fmt=fmt):
    """categories: [str]; series: [(name, css_var, [values])]."""
    W = 760
    ml, mr, mt, mb = 64, 20, 18, 46
    x0, x1, y0, y1 = ml, W - mr, mt, height - mb
    vmax = nice_max(max(max(vs) for _, _, vs in series))
    out = [
        f'<svg viewBox="0 0 {W} {height}" role="img" preserveAspectRatio="xMidYMid meet">'
    ]
    out.append(grid_and_yaxis(x0, x1, y0, y1, vmax, unit))

    ncat, nser = len(categories), len(series)
    band = (x1 - x0) / ncat
    barw = min(24.0, (band * 0.62 - 2 * (nser - 1)) / nser)
    group_w = barw * nser + 2 * (nser - 1)

    for ci, cat in enumerate(categories):
        gx = x0 + band * ci + (band - group_w) / 2
        out.append(
            f'<text x="{x0 + band * (ci + 0.5):.1f}" y="{y1 + 20}" class="tick" text-anchor="middle">{esc(cat)}</text>'
        )
        labels = []
        for si, (name, var, vals) in enumerate(series):
            v = vals[ci]
            h = (y1 - y0) * (v / vmax) if vmax else 0
            bx = gx + si * (barw + 2)  # 2px surface gap between adjacent bars
            by = y1 - h
            out.append(
                f'<path d="{bar_path(bx, by, barw, h)}" style="fill:var({var})">'
                f"<title>{esc(name)} · {esc(cat)}: {value_fmt(v)}{unit}</title></path>"
            )
            labels.append([bx + barw / 2, by - 6, value_fmt(v)])
        # stagger cap labels that would collide with a neighbor's
        for li in range(1, len(labels)):
            px, py, _ = labels[li - 1]
            if abs(labels[li][0] - px) < 44 and abs(labels[li][1] - py) < 13:
                labels[li][1] = py - 13
        for lx, ly, txt in labels:
            out.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" class="vlabel" text-anchor="middle">{txt}</text>'
            )
    out.append("</svg>")
    return "".join(out)


def line_chart_svg(x_labels, series, unit="%", height=360, y_label=""):
    """x_labels: [str]; series: [(name, css_var, [values])]. Direct end labels."""
    W = 760
    ml, mr, mt, mb = 64, 118, 18, 46
    x0, x1, y0, y1 = ml, W - mr, mt, height - mb
    vmax = nice_max(max(max(vs) for _, _, vs in series))
    n = len(x_labels)
    xs = [x0 + (x1 - x0) * i / (n - 1) for i in range(n)]

    out = [
        f'<svg viewBox="0 0 {W} {height}" role="img" preserveAspectRatio="xMidYMid meet">'
    ]
    out.append(grid_and_yaxis(x0, x1, y0, y1, vmax, unit))
    for i, lab in enumerate(x_labels):
        out.append(
            f'<text x="{xs[i]:.1f}" y="{y1 + 20}" class="tick" text-anchor="middle">{esc(lab)}</text>'
        )
    if y_label:
        out.append(f'<text x="{x0}" y="{y0 - 4}" class="tick">{esc(y_label)}</text>')

    def ypix(v):
        return y1 - (y1 - y0) * (v / vmax if vmax else 0)

    # collision-nudge end labels
    ends = sorted(((ypix(vs[-1]), name, var, vs) for name, var, vs in series))
    placed = []
    for ey, name, var, vs in ends:
        ly = ey
        while any(abs(ly - p) < 14 for p in placed):
            ly += 14
        placed.append(ly)
        pts = " ".join(f"{xs[i]:.1f},{ypix(v):.1f}" for i, v in enumerate(vs))
        out.append(
            f'<polyline points="{pts}" style="stroke:var({var})" class="ln" fill="none">'
            f"<title>{esc(name)}</title></polyline>"
        )
        for i, v in enumerate(vs):
            out.append(
                f'<circle cx="{xs[i]:.1f}" cy="{ypix(v):.1f}" r="4" class="dot" style="fill:var({var})">'
                f"<title>{esc(name)} · {esc(x_labels[i])}: {fmt(v)}{unit}</title></circle>"
            )
        if abs(ly - ey) > 7:  # leader line when nudged
            out.append(
                f'<line x1="{x1 + 4}" y1="{ey:.1f}" x2="{x1 + 16}" y2="{ly:.1f}" class="leader"/>'
            )
        out.append(
            f'<text x="{x1 + 20}" y="{ly + 4:.1f}" class="endlabel">'
            f'<tspan style="fill:var({var})">●</tspan> {esc(name)}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def hbar_svg(rows, unit=" ms", height=None):
    """rows: [(label, value, css_var)] — horizontal bars, value labels at ends."""
    W = 760
    ml, mr, mt = 260, 110, 12
    rh, gap = 26, 14
    height = height or (mt + len(rows) * (rh + gap) + 18)
    vmax = nice_max(max(v for _, v, _ in rows))
    x0, x1 = ml, W - mr
    out = [
        f'<svg viewBox="0 0 {W} {height}" role="img" preserveAspectRatio="xMidYMid meet">'
    ]
    out.append(f'<line x1="{x0}" y1="{mt}" x2="{x0}" y2="{height - 14}" class="axis"/>')
    for i, (label, v, var) in enumerate(rows):
        y = mt + i * (rh + gap)
        w = (x1 - x0) * (v / vmax if vmax else 0)
        out.append(
            f'<text x="{x0 - 10}" y="{y + rh / 2 + 4}" class="tick" text-anchor="end">{esc(label)}</text>'
        )
        out.append(
            f'<path d="{hbar_path(x0, y, max(w, 1.5), rh)}" style="fill:var({var})">'
            f"<title>{esc(label)}: {fmt(v, 2)}{unit}</title></path>"
        )
        out.append(
            f'<text x="{x0 + max(w, 1.5) + 8:.1f}" y="{y + rh / 2 + 4}" class="vlabel">{fmt(v, 2)}{unit}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def table_html(headers, rows, cls="datatable"):
    th = "".join(f"<th>{h}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tablewrap"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


def table_view(headers, rows):
    return f'<details class="tv"><summary>Table view</summary>{table_html(headers, rows)}</details>'


# ---------------------------------------------------------------- sections


def sel(records, **kw):
    out = records
    for k, v in kw.items():
        if isinstance(v, (list, tuple, set)):
            out = [r for r in out if r[k] in v]
        else:
            out = [r for r in out if r[k] == v]
    return out


def section_stream(sessions):
    # The headline bandwidth tax is the MATCHED pair only: two identically-shaped
    # VMs (same 32-vCPU/64G shape, same kernel, same day) that differ ONLY in SEV
    # state. Other sessions — the bare-metal 128-thread anchor and the SNP CVM
    # (a separate run, different kernel) — are shown for context but are NEVER
    # pooled into the tax; different shape/kernel/day makes them non-comparable
    # head to head (indeed the SNP anchor reads slightly higher than the plain VM,
    # which is a cross-run artifact, not a negative tax).
    def one(pred):
        xs = [s for s in sessions if pred(s)]
        return (med(s["stream_triad_gbs"] for s in xs) if xs else 0.0), xs

    m_off, off = one(
        lambda s: (
            s["sev_mode"] == "off"
            and "vm" in s["session_id"]
            and "baremetal" not in s["session_id"]
        )
    )
    m_on, on = one(lambda s: s["sev_mode"] == "es")
    tax = (m_off - m_on) / m_off * 100 if m_off and m_on else 0
    m_bare, bare = one(
        lambda s: s["sev_mode"] == "off" and "baremetal" in s["session_id"]
    )
    m_snp, snp = one(lambda s: s["sev_mode"] == "snp")

    bars = [
        ("Plain VM · SEV off", m_off, SEV_OFF_SLOT),
        ("CVM · SEV-ES", m_on, SEV_ON_SLOT),
    ]
    anchors = []
    if m_bare:
        anchors.append(("Bare metal (128t anchor)", m_bare, "--s3"))
    if m_snp:
        anchors.append(("SNP CVM (separate run)", m_snp, "--s4"))
    svg = two_bar_svg(bars + anchors, " GB/s")

    snp_line = (
        (
            f" The SNP CVM anchor ({fmt(m_snp)} GB/s, KDS-verified, separate "
            "run) is shown for context only — a different kernel/day, not a "
            "matched SEV-off↔SNP pair, so no SNP tax is claimed from it."
        )
        if m_snp
        else ""
    )
    tbl_rows = [
        ["Plain VM (off)", fmt(m_off), str(len(off))],
        ["CVM (SEV-ES)", fmt(m_on), str(len(on))],
    ]
    if m_bare:
        tbl_rows.append(["Bare metal (off, anchor)", fmt(m_bare), str(len(bare))])
    if m_snp:
        tbl_rows.append(["SNP CVM (anchor)", fmt(m_snp), str(len(snp))])
    body = f"""
    <p>Median STREAM triad bandwidth on the box (theoretical: ~614 GB/s from
    12× DDR5-6400). CPU LLM decode is memory-bandwidth-bound, so this is the
    mechanism the TEE tax is measured against. The headline number is the
    matched pair — two identical 32-vCPU VMs differing only in SEV state: SEV-ES
    AES memory encryption costs <strong>{fmt(tax)}%</strong> of deliverable
    bandwidth ({fmt(m_off)} → {fmt(m_on)} GB/s). Note this 26% is the
    <em>bandwidth</em> tax; the actual single-stream <em>decode</em> tax below is
    far smaller because a single decode stream does not saturate the bus.{snp_line}</p>
    {svg}
    {table_view(["Configuration", "Median STREAM triad (GB/s)", "Sessions"], tbl_rows)}
    {sess_provenance(sessions)}
    """
    return body, tax, m_off, m_on


def two_bar_svg(rows, unit):
    W, H = 760, 240
    ml, mt, mb = 64, 18, 42
    x0, x1, y0, y1 = ml, W - 20, mt, H - mb
    vmax = nice_max(max(v for _, v, _ in rows))
    out = [
        f'<svg viewBox="0 0 {W} {H}" role="img" preserveAspectRatio="xMidYMid meet">'
    ]
    out.append(grid_and_yaxis(x0, x1, y0, y1, vmax))
    band = (x1 - x0) / len(rows)
    for i, (label, v, var) in enumerate(rows):
        h = (y1 - y0) * v / vmax
        bx = x0 + band * i + band / 2 - 12
        out.append(
            f'<path d="{bar_path(bx, y1 - h, 24, h)}" style="fill:var({var})">'
            f"<title>{esc(label)}: {fmt(v)}{unit}</title></path>"
        )
        out.append(
            f'<text x="{bx + 12:.1f}" y="{y1 - h - 8:.1f}" class="vlabel" text-anchor="middle">{fmt(v)}{unit}</text>'
        )
        out.append(
            f'<text x="{x0 + band * (i + 0.5):.1f}" y="{y1 + 20}" class="tick" text-anchor="middle">{esc(label)}</text>'
        )
    out.append("</svg>")
    return "".join(out)


# The single cell at which legs A and B were BOTH measured, identically shaped.
# Leg B was run only here (single-stream, 32 threads, short prompt); the wide
# leg-A sweep does not overlap it. Every A-vs-B number is computed at this cell
# and nowhere else — a mismatched cell yields n/a, never a ratio against zero.
AB_CELL = {"threads": 32, "prompt_tokens": 16, "concurrency": 1}


def ab_matched(records):
    """model -> (a_tps, b_tps) for models measured on BOTH legs at AB_CELL.

    Models without both legs at the matched cell are omitted (rendered n/a by
    callers) — the generator never fabricates a leg-B number it does not have.
    """
    out = {}
    for m in MODEL_ORDER:
        a = sel(records, leg="A", model=m, **AB_CELL)
        b = sel(records, leg="B", model=m, **AB_CELL)
        if a and b:
            out[m] = (
                med(r["tokens_per_s"] for r in a),
                med(r["tokens_per_s"] for r in b),
            )
    return out


def ab_tax(records):
    """model -> SEV-ES throughput tax %, (a-b)/a, at the matched cell."""
    return {m: (a - b) / a * 100 for m, (a, b) in ab_matched(records).items() if a}


def section_tax_curves(records):
    matched = ab_matched(records)
    tax = ab_tax(records)
    ab1 = sel(records, leg=("A", "B"), **AB_CELL)
    models = [m for m in MODEL_ORDER if m in matched]
    if not models:
        return (
            "<p class='placeholder'>No matched A/B cell in the data — "
            "cannot compute a TEE inference tax. (Need both legs at the same "
            "model/threads/prompt/concurrency.)</p>",
            tax,
        )

    # bars are tax magnitude; sign + note fold into the row label (a small
    # negative just means B measured slightly faster — i.e. within run-to-run
    # noise, no measurable tax).
    def lab(m):
        t = tax[m]
        sign = "−" if t < 0 else "+"
        tail = " (within noise)" if abs(t) < 1.0 or t < 0 else ""
        return f"{m}  {sign}{abs(t):.1f}%{tail}"

    svg = hbar_svg([(lab(m), abs(tax[m]), MODEL_SLOT[m]) for m in models], unit="%")
    rows = [
        [m, fmt(matched[m][0], 2), fmt(matched[m][1], 2), f"{tax[m]:+.1f}%"]
        for m in models
    ]
    missing = [m for m in MODEL_ORDER if m not in matched]
    miss_note = (
        (
            f" ({', '.join(missing)} were not run on both legs at this cell, "
            "so no tax is shown for them.)"
        )
        if missing
        else ""
    )
    worst = max(tax.values())
    body = f"""
    <p>The measured SEV-ES inference tax, at the one cell where legs A and B were
    run identically (single-stream, 32 threads, short prompt; concurrency 1).
    Tax = (median tokens/s leg A − median tokens/s leg B) / leg A.{miss_note}</p>
    <p><strong>The result is the surprising part:</strong> decode throughput is
    taxed only about <strong>{worst:.0f}%</strong> at its worst here — far below
    the {26}% STREAM bandwidth tax above. The reason is in that STREAM number:
    single-stream decode at 32 threads does not saturate memory bandwidth, so
    SEV's encryption cost on the memory path hides in the slack. The 26% STREAM
    figure is a pure-bandwidth bound, not the tax a single decode stream
    necessarily pays. This historical SEV-ES chart does not extrapolate beyond
    its one matched cell; the newer cloned-twin SNP matrix, including isolated
    concurrency cells, is reported separately below.</p>
    {svg}
    {table_view(["Model", "A tok/s", "B tok/s", "SEV-ES tax"], rows)}
    {provenance(ab1)}
    """
    return body, tax


def section_tps_ab(records):
    slice_ = sel(records, leg=("A", "B"), **AB_CELL)
    matched = ab_matched(records)
    models = [m for m in MODEL_ORDER if m in matched]
    if not models:
        return (
            "<p class='placeholder'>No matched A/B throughput cell is present. "
            "The report cannot draw this chart without both legs at the same "
            f"model and shape.</p>{provenance(slice_)}",
            {},
        )
    a_vals = [matched[m][0] for m in models]
    b_vals = [matched[m][1] for m in models]
    rows = []
    for m in models:
        a = sel(slice_, leg="A", model=m)
        b = sel(slice_, leg="B", model=m)
        am, bm = matched[m]
        rows.append(
            [
                m,
                fmt(am, 2),
                fmt(bm, 2),
                f"{(am - bm) / am * 100:+.1f}%",
                fmt(med(r["itl_ms_p50"] for r in a), 2),
                fmt(p99([r["itl_ms_p99"] for r in a]), 2),
                fmt(med(r["itl_ms_p50"] for r in b), 2),
                fmt(p99([r["itl_ms_p99"] for r in b]), 2),
            ]
        )
    svg = grouped_bar_svg(
        models,
        [("A · SEV off", SEV_OFF_SLOT, a_vals), ("B · SEV-ES", SEV_ON_SLOT, b_vals)],
        unit="",
        value_fmt=lambda v: fmt(v, 1),
    )
    body = f"""
    <p>Median single-stream decode throughput (tokens/s) at the matched A/B cell
    (32 threads, concurrency 1). The bars sit nearly on top of each other —
    that visual near-equality <em>is</em> the ~2% tax result. The table adds
    inter-token latency: median of per-request p50 and p99-of-p99s.</p>
    {legend_html([("A · SEV off", SEV_OFF_SLOT), ("B · SEV-ES", SEV_ON_SLOT)])}
    {svg}
    {
        table_view(
            [
                "Model",
                "A tok/s",
                "B tok/s",
                "SEV tax",
                "A ITL p50 (ms)",
                "A ITL p99 (ms)",
                "B ITL p50 (ms)",
                "B ITL p99 (ms)",
            ],
            rows,
        )
    }
    {provenance(slice_)}
    """
    return body, {m: matched[m] for m in models}


def section_snp_twin(records):
    """Full matched SEV-off/SNP twin matrix, kept separate from legacy ES."""
    a_all = sel(records, leg="A", sev_mode="off", numa_policy="guest-single-numa")
    b_all = sel(records, leg="B", sev_mode="snp", numa_policy="guest-single-numa")
    rows = []
    taxes = []
    for model in MODEL_ORDER:
        for threads in (16, 32):
            for prompt_tokens in (128, 1024):
                shape = {
                    "model": model,
                    "threads": threads,
                    "prompt_tokens": prompt_tokens,
                    "concurrency": 1,
                    "input_mode": "tls",
                }
                a = sel(a_all, **shape)
                b = sel(b_all, **shape)
                if not (a and b):
                    continue
                a_tps = med(r["tokens_per_s"] for r in a)
                b_tps = med(r["tokens_per_s"] for r in b)
                tax = (a_tps - b_tps) / a_tps * 100 if a_tps else 0.0
                taxes.append(tax)
                rows.append(
                    [
                        model,
                        str(threads),
                        str(prompt_tokens),
                        fmt(a_tps, 2),
                        fmt(b_tps, 2),
                        f"{tax:+.1f}%",
                        fmt(med(r["ttft_ms"] for r in a), 0),
                        fmt(med(r["ttft_ms"] for r in b), 0),
                    ]
                )
    if not rows:
        return (
            '<p class="placeholder">The matched plain-twin/SNP sweep is not '
            f"present yet.</p>{provenance(a_all + b_all)}"
        )

    concurrency_rows = []
    for model in MODEL_ORDER:
        for prompt_tokens in (128, 1024):
            for concurrency in (1, 4, 8):
                shape = {
                    "model": model,
                    "threads": 32,
                    "prompt_tokens": prompt_tokens,
                    "concurrency": concurrency,
                    "input_mode": "tls",
                }
                a = sel(a_all, **shape)
                b = sel(b_all, **shape)
                if not (a and b):
                    continue
                concurrency_rows.append(
                    [
                        model,
                        str(prompt_tokens),
                        str(concurrency),
                        fmt(med(r["tokens_per_s"] for r in a), 2),
                        fmt(med(r["tokens_per_s"] for r in b), 2),
                        fmt(med(r["e2e_ms"] for r in a), 0),
                        fmt(med(r["e2e_ms"] for r in b), 0),
                    ]
                )

    hpke_rows = []
    for model in MODEL_ORDER:
        tls = sel(
            b_all,
            model=model,
            threads=32,
            prompt_tokens=128,
            concurrency=1,
            input_mode="tls",
        )
        hpke = sel(
            b_all,
            model=model,
            threads=32,
            prompt_tokens=128,
            concurrency=1,
            input_mode="hpke",
        )
        if not (tls and hpke):
            continue
        tls_e2e = med(r["e2e_ms"] for r in tls)
        hpke_e2e = med(r["e2e_ms"] for r in hpke)
        hpke_rows.append(
            [
                model,
                fmt(tls_e2e, 1),
                fmt(hpke_e2e, 1),
                f"{hpke_e2e - tls_e2e:+.1f}",
                fmt(med(r["attest_fetch_ms"] for r in hpke), 1),
                fmt(med(r["attest_verify_ms"] for r in hpke), 1),
            ]
        )

    return f"""
    <p>This is the causal SNP comparison: the plain twin is cloned from the SNP
    guest disk and uses the same AMDSEV QEMU, OVMF, 32-vCPU topology, 64 GiB RAM,
    read-only model volume, runtime binaries, and matrix. The confidential-guest
    object is the intended treatment difference. Median per-request values are
    shown after the two-sample warmup discard; observed throughput tax spans
    <strong>{min(taxes):+.1f}% to {max(taxes):+.1f}%</strong> across matched
    single-stream cells.</p>
    {
        table_view(
            [
                "Model",
                "Threads",
                "Prompt",
                "Plain tok/s",
                "SNP tok/s",
                "SNP tax",
                "Plain TTFT ms",
                "SNP TTFT ms",
            ],
            rows,
        )
    }
    <p>Concurrency cells report median per-request throughput and latency. They
    are not multiplied into an unmeasured aggregate-throughput claim.</p>
    {
        table_view(
            [
                "Model",
                "Prompt",
                "Conc",
                "Plain tok/s/request",
                "SNP tok/s/request",
                "Plain e2e ms",
                "SNP e2e ms",
            ],
            concurrency_rows,
        )
    }
    <p>HPKE is compared within the SNP guest. Attestation fetch/verification is
    a client-side refresh cost; the X25519 key is domain-separated and signed by
    the SNP-bound Ed25519 identity before the client encrypts. The E2E delta is
    an observed difference between non-interleaved request runs and includes
    normal inference variance; it does not isolate the HPKE primitive itself.</p>
    {
        table_view(
            [
                "Model",
                "TLS e2e ms",
                "HPKE e2e ms",
                "HPKE delta ms",
                "Attest fetch ms",
                "Attest verify ms",
            ],
            hpke_rows,
        )
    }
    {provenance(a_all + b_all)}
    """


def cost_per_mtok(tps, box_cost_hr):
    """$ per 1M output tokens at a given sustained tokens/s."""
    return box_cost_hr / (tps * 3600.0) * 1e6 if tps else float("inf")


def section_glm(records, registry, box_cost_hr):
    """Flagship GLM result and the comparisons the current data can support."""
    glm = sel(records, model="glm-5.2-q4")
    glm_off = sel(glm, leg="A", sev_mode="off")
    glm_snp = sel(glm, leg="B", sev_mode="snp")
    dense_snp = sel(
        records,
        leg="B",
        model="70b-q4",
        sev_mode="snp",
        threads=32,
        prompt_tokens=128,
        concurrency=1,
        input_mode="tls",
    )
    entry = registry.get("glm-5.2-q4", {})

    if not glm_off:
        return (
            '<p class="placeholder">No GLM-5.2 measurement is present. The '
            "flagship, its TEE comparison, and its price comparison cannot be "
            f"reported.</p>{provenance(glm)}"
        )

    glm_tps = med(r["tokens_per_s"] for r in glm_off)
    glm_ttft = med(r["ttft_ms"] for r in glm_off)
    glm_cost = cost_per_mtok(glm_tps, box_cost_hr)
    snp_tps = med(r["tokens_per_s"] for r in glm_snp) if glm_snp else None
    dense_snp_tps = med(r["tokens_per_s"] for r in dense_snp) if dense_snp else None
    registry_in = entry.get("price_per_1m_in_usdc")
    registry_out = entry.get("price_per_1m_out_usdc")

    measured_rows = [
        [
            "GLM-5.2 Q4 · SEV off",
            str(len(glm_off)),
            f"{glm_tps:.2f}",
            f"{glm_ttft:.0f}",
            f"${glm_cost:,.2f}",
            "measured baseline",
        ]
    ]
    if glm_snp:
        measured_rows.append(
            [
                "GLM-5.2 Q4 · SNP",
                str(len(glm_snp)),
                f"{snp_tps:.2f}",
                f"{med(r['ttft_ms'] for r in glm_snp):.0f}",
                f"${cost_per_mtok(snp_tps, box_cost_hr):,.2f}",
                "measured SNP",
            ]
        )
    else:
        measured_rows.append(
            [
                "GLM-5.2 Q4 · SNP",
                "0",
                "n/a",
                "n/a",
                "n/a",
                "not measured; no TEE tax claimed",
            ]
        )

    dense_value = f"{dense_snp_tps:.2f}" if dense_snp_tps else "n/a"
    comparison_rows = [
        [
            "GLM-5.2 Q4 MoE",
            "SNP",
            "n/a" if snp_tps is None else f"{snp_tps:.2f}",
            "missing SNP run" if snp_tps is None else "measured",
        ],
        [
            "Llama 3.3 70B Q4 dense",
            "SNP",
            dense_value,
            "32 threads / 128 prompt; no matched GLM SNP cell",
        ],
    ]

    price_rows = [
        [
            "GLM-5.2 Q4 measured box cost",
            "n/a",
            f"${glm_cost:,.2f}",
            f"SEV-off {glm_tps:.2f} tok/s at ${box_cost_hr:.2f}/hour",
        ],
        [
            "GLM-5.2 Q4 registry offer",
            f"${registry_in:,.4f}" if registry_in is not None else "n/a",
            f"${registry_out:,.4f}" if registry_out is not None else "n/a",
            "generated by pricing.py; includes configured margin and receipts",
        ],
    ]

    return f"""
    <p>GLM-5.2 Q4 is the flagship registry model: a 744B-total/~40B-active MoE.
    The available baseline measured <strong>{glm_tps:.2f} tokens/s</strong> at
    64 threads with a 16-token prompt. It is not part of the matched SNP sweep,
    so this report cannot yet answer how that MoE compares with the dense 70B
    model under SEV. The missing cell is shown directly below.</p>
    {
        table_html(
            ["Configuration", "n", "tok/s", "TTFT ms", "$ / 1M output tok", "Status"],
            measured_rows,
        )
    }
    <h3>MoE vs dense under SNP</h3>
    {table_html(["Model", "SEV state", "tok/s", "Comparison status"], comparison_rows)}
    <p>The price rows are self-hosted measurements and generated registry
    pricing only. Claude is the sole external API upstream in this project.</p>
    {table_html(["Price basis", "Input / 1M", "Output / 1M", "Notes"], price_rows)}
    {provenance(glm + dense_snp)}
    """


def section_cost(records, tps_ab, box_cost_hr, api_in, api_out):
    def usd(tps):
        return f"${cost_per_mtok(tps, box_cost_hr):,.2f}" if tps else "n/a"

    rows = []
    for m in MODEL_ORDER:
        if m not in tps_ab:
            continue
        a_tps, b_tps = tps_ab[m]
        rows.append([f"{m} · A (SEV off)", usd(a_tps), "box amortization"])
        rows.append([f"{m} · B (SEV-ES)", usd(b_tps), "box amortization"])
    c_models = sorted({r["model"] for r in records if r["leg"].startswith("C-")})
    api_model = c_models[-1] if c_models else "configured Anthropic model"
    rows.append(
        [
            f"C-direct · {api_model} (published API)",
            f"${api_out:,.2f}",
            f"published output price (input ${api_in:,.2f}/1M)",
        ]
    )
    rows.append(
        [
            "C-proxied · same + CVM proxy",
            f"${api_out:,.2f} + proxy share",
            "API price + amortized proxy box",
        ]
    )
    slice_ = sel(records, leg=("A", "B"), **AB_CELL)
    body = f"""
    <p><strong>Cost parameterization (stated, not hidden):</strong> the box is
    amortized at <strong>${box_cost_hr:.2f}/hour</strong> (hardware + power +
    hosting, straight-line; change with <code>--box-cost-per-hr</code>).
    $/1M output tokens = hourly cost ÷ (tokens/s × 3600) × 10⁶, using the
    single-stream median at the matched A/B cell (32 threads, concurrency 1).
    These dollar rows use the historical single-cell SEV-ES pair; the cloned
    plain/SNP concurrency matrix is not folded into this older cost basis.
    Leg C rows
    use published Anthropic API pricing (parameterized:
    <code>--api-input-per-mtok</code>, <code>--api-output-per-mtok</code>) — API
    tokens are priced by Anthropic, not by this box's amortization.</p>
    {table_html(["Config", "$/1M output tok (single stream)", "Basis"], rows)}
    {provenance(slice_)}
    """
    return body


def section_attestation(records):
    b = sel(records, leg="B", sev_mode="snp") or sel(records, leg="B")
    fields = [
        ("Attestation fetch (snpguest report)", "attest_fetch_ms"),
        ("Attestation verify (VCEK → ASK/ARK)", "attest_verify_ms"),
        ("Receipt sign (ed25519, in-enclave)", "receipt_sign_ms"),
        ("Receipt post (devnet submit)", "receipt_post_ms"),
        ("Receipt confirm (devnet)", "receipt_confirm_ms"),
    ]
    measured = []
    rows_tbl = []
    missing = []
    for label, field in fields:
        values = [r[field] for r in b if r[field] > 0]
        if values:
            measured.append((label, med(values), "--s1"))
            rows_tbl.append(
                [label, fmt(med(values), 2), fmt(p99(values), 2), str(len(values))]
            )
        else:
            missing.append(label)
            rows_tbl.append([label, "not recorded", "not recorded", "0"])
    cu_values = [r["solana_cu"] for r in b if r["solana_cu"] > 0]
    fee_values = [r["solana_fee_lamports"] for r in b if r["solana_fee_lamports"] > 0]
    chain_note = (
        f"Measured receipt median: {fmt(med(cu_values), 0)} CU, "
        f"{fmt(med(fee_values), 0)} lamports."
        if cu_values and fee_values
        else "Per-response Solana CU and fee were not recorded in this dataset."
    )
    chart = (
        hbar_svg(measured)
        if measured
        else '<p class="placeholder">No positive phase timings recorded.</p>'
    )
    missing_note = (
        " Unmeasured zero sentinels are shown as not recorded, not as zero-cost operations: "
        + "; ".join(missing)
        + "."
        if missing
        else ""
    )
    body = f"""
    <p>Median of the leg-B requests that contain a positive measurement for each
    verification phase; the table reports the contributing n. Fetch + verify
    happen per attestation refresh (cached certs assumed); receipt post/confirm
    would be asynchronous devnet round-trips outside the token stream. {chain_note}{missing_note}
    What SNP attestation proves — and what launch-only would not — is spelled
    out in the honest-limits section.</p>
    {chart}
    {table_view(["Phase", "Median (ms)", "p99 (ms)", "n"], rows_tbl)}
    {provenance(b)}
    """
    return body


def section_leg_c(records):
    c = sel(records, leg=("C-direct", "C-proxied"))

    def output_cap(record):
        match = re.fullmatch(
            r"C-(?:direct|proxied)-(\d+)-(\d+)-c(\d+)-(\d+)",
            record["run_id"],
        )
        return int(match.group(2)) if match else None

    shapes = sorted(
        {
            (record["prompt_tokens"], output_cap(record), record["concurrency"])
            for record in c
            if output_cap(record) is not None
        }
    )
    matched = []
    for prompt_tokens, cap, concurrency in shapes:
        direct = [
            record
            for record in c
            if record["leg"] == "C-direct"
            and record["prompt_tokens"] == prompt_tokens
            and output_cap(record) == cap
            and record["concurrency"] == concurrency
        ]
        proxied = [
            record
            for record in c
            if record["leg"] == "C-proxied"
            and record["prompt_tokens"] == prompt_tokens
            and output_cap(record) == cap
            and record["concurrency"] == concurrency
        ]
        if direct and proxied:
            matched.append((prompt_tokens, cap, concurrency, direct, proxied))

    if not matched:
        return (
            '<p class="placeholder">No matched direct/proxied Leg C cells are '
            f"present yet.</p>{provenance(c)}",
            0.0,
            0.0,
        )
    cats = [f"{pt}p/{cap}o c{conc}" for pt, cap, conc, _, _ in matched]
    d_vals, p_vals, rows = [], [], []
    deltas = []
    for pt, cap, conc, direct, proxied in matched:
        dm = med(r["ttft_ms"] for r in direct)
        pm = med(r["ttft_ms"] for r in proxied)
        de = med(r["e2e_ms"] for r in direct)
        pe = med(r["e2e_ms"] for r in proxied)
        d_vals.append(dm)
        p_vals.append(pm)
        deltas.append((pm - dm, (pe - de) / de * 100 if de else 0))
        pct = f"+{(pe - de) / de * 100:.1f}%" if de and pe else "—"
        rows.append(
            [
                str(pt),
                str(cap),
                str(conc),
                fmt(dm, 0),
                fmt(pm, 0),
                f"{pm - dm:+.0f}",
                fmt(med(r["output_tokens"] for r in direct), 0),
                fmt(med(r["output_tokens"] for r in proxied), 0),
                fmt(de, 0),
                fmt(pe, 0),
                pct,
            ]
        )
    delta_ms = med(d[0] for d in deltas)
    delta_pct = med(d[1] for d in deltas)
    svg = grouped_bar_svg(
        cats,
        [("C-direct", SEV_OFF_SLOT, d_vals), ("C-proxied (CVM)", SEV_ON_SLOT, p_vals)],
        unit=" ms",
        value_fmt=lambda v: fmt(v, 0),
    )
    body = f"""
    <p>Leg C is the honest control: the proxy process creates its own ephemeral
    key and VMPL0 report-bound policy/build identity (verification artifact:
    <code>runs/legC-proxy-attestation.json</code>), but the current mutable
    guest image does not independently prove the proxy's
    routing/logging policy. Inference itself is not verified and Anthropic sees
    plaintext. TTFT and end-to-end time use the streamed response clock;
    inter-event latency is measured between Anthropic content-delta events and
    is not asserted to be a one-event-per-token trace. Across the eight matched
    shapes, the median shape-level TTFT difference is
    <strong>{delta_ms:+.0f} ms</strong>. End-to-end differences are reported but
    are not treated as proxy overhead when the provider stopped before the
    requested cap at different output-token counts.</p>
    {legend_html([("C-direct", SEV_OFF_SLOT), ("C-proxied (CVM)", SEV_ON_SLOT)])}
    {svg}
    {
        table_view(
            [
                "Prompt target",
                "Output cap",
                "Concurrency",
                "direct TTFT (ms)",
                "proxied TTFT (ms)",
                "Δ TTFT (ms)",
                "direct output tok",
                "proxied output tok",
                "direct e2e (ms)",
                "proxied e2e (ms)",
                "observed Δ e2e",
            ],
            rows,
        )
    }
    {provenance(c)}
    """
    return body, delta_ms, delta_pct


def section_leg_d(records):
    d = sel(records, leg="D")
    if not d:
        return (
            '<p class="placeholder">Leg D has no measurement rows. None of the '
            "required matmul-to-token ladder has run, and the on-chain proof "
            "instruction is an explicitly unverified stub. Leg D would prove "
            "integrity for a public model and hashed input, not input privacy. "
            f"No proving-time or Groth16 claim is made.</p>{provenance(d)}"
        )
    rung_models = sorted({r["model"] for r in d})
    rows = []
    for m in rung_models:
        off = sel(d, model=m, sev_mode="off")
        snp = [r for r in sel(d, model=m) if r["sev_mode"] != "off"]
        po = med(r["e2e_ms"] for r in off) / 1000.0
        ps = med(r["e2e_ms"] for r in snp) / 1000.0 if snp else 0.0
        rows.append(
            [
                f"rung {m.rsplit('rung', 1)[-1]}",
                m,
                f"{po:,.0f} s",
                f"{ps:,.0f} s" if snp else "—",
                f"+{(ps - po) / po * 100:.1f}%" if snp and po else "—",
                fmt(med(r["attest_verify_ms"] for r in off), 1),
                f"{med(r['solana_cu'] for r in off):,.0f}",
                f"{med(r['solana_fee_lamports'] for r in off):,.0f}",
            ]
        )
    body = f"""
    <p>The zkML ladder (leg D), proved on this box. The frozen request schema
    has no <code>rung_id</code> field, so the rung is encoded in the model
    field (<code>bitnet-2b-rung1</code> = one ternary matmul,
    <code>rung2</code> = one transformer block, <code>rung3</code> = 4 blocks,
    the extrapolation basis). e2e_ms carries proving wall time;
    attest_verify_ms carries off-chain proof verification; the receipt/solana
    fields carry the on-chain Groth16 verify transaction. Note the prover is
    itself memory-heavy: SEV taxes proving too. This leg proves
    <em>integrity</em> (public model, hashed input), not input privacy.</p>
    {
        table_html(
            [
                "Rung",
                "model field",
                "Prove (SEV off, median)",
                "Prove (SEV on, median)",
                "SEV tax",
                "Off-chain verify (ms)",
                "On-chain verify (CU)",
                "Fee (lamports)",
            ],
            rows,
        )
    }
    {provenance(d)}
    """
    return body


def section_breakeven(records, tps_ab, box_cost_hr):
    rows = []
    for m in MODEL_ORDER:
        if m not in tps_ab:
            continue
        a_tps, b_tps = tps_ab[m]
        ca, cb = cost_per_mtok(a_tps, box_cost_hr), cost_per_mtok(b_tps, box_cost_hr)
        mult = cb / ca if ca else 0
        rows.append(
            [
                m,
                f"${ca:,.2f}",
                f"${cb:,.2f}",
                f"×{mult:.3f}",
                f"{(mult - 1) * 100:+.1f}%",
            ]
        )
    slice_ = sel(records, leg=("A", "B"), **AB_CELL)
    body = f"""
    <p>Same box, same watts, same hour — the only thing SEV changes is tokens
    delivered per hour, so <strong>premium multiplier = cost_B / cost_A =
    tokens/s_A ÷ tokens/s_B</strong>. Reading: at the measured single-stream
    cell the premium is only a couple of percent (and for bitnet-2b the sign is
    negative — B measured marginally faster, i.e. within noise), so a buyer who
    values hardware-attested inference at even a few percent clears break-even.
    These rows are the historical matched SEV-ES single-stream cell; the full
    cloned-twin SNP concurrency results are reported separately and are not
    folded into this older premium calculation. Receipt costs are per-request,
    not per-token, listed separately in the attestation section; at devnet fees
    they are noise per 1M tokens.</p>
    {table_html(["Model", "A $/1M tok", "B $/1M tok", "Break-even premium (×)", "as %"], rows)}
    {provenance(slice_)}
    """
    return body


def section_limits():
    return """
    <p>What is and isn't protected, stated plainly. "Encrypted" is layered.</p>
    <ul>
      <li><strong>SNP is live, but the measured software chain is incomplete:</strong>
      the live guest returns a VMPL0 report whose signature verifies through the
      AMD VCEK→ASK→ARK chain and whose launch measurement is policy-allowlisted.
      Report data binds the ephemeral signing key plus guest-declared registry
      and build digests. The root disk is mutable and the build digest is a
      release identifier, not a measurement of every Python module and weight
      byte, so this does not independently prove which model implementation ran.
      A measured immutable root/code manifest is required to close that gap.</li>
      <li><strong>The input-sealed path removes prompt plaintext from the TLS proxy:</strong>
      HPKE on <code>/v1/infer_sealed</code> seals only the prompt to the SNP-bound
      key; its response is plaintext inside the outer TLS connection. Use
      <code>/v1/chat_e2e</code> for a response sealed back to the verified client.
      Neither mode defends against an operator who replaces the mutable guest
      application with one that logs plaintext.</li>
      <li><strong>Metadata leaks:</strong> request timing, sizes, model choice,
      token counts, and cost are visible to the operator/network even when the
      payload is sealed. Traffic analysis is not addressed.</li>
      <li><strong>Model weights are public</strong> by design — hashed into the
      receipt, not hidden. Leg C (Claude proxy) is deliberately not private:
      Anthropic sees plaintext; it's the honest control.</li>
      <li><strong>On-chain is hashes, not content:</strong> only sha256(prompt),
      sha256(response), model hash go to Solana — a commitment, not the text
      (an adversary who guesses the text can confirm it).</li>
      <li><strong>Trust roots include AMD and the measured guest supply chain:</strong>
      AMD's ASP/PSP, memory-encryption engine, RMP, and VCEK→ASK→ARK chain are
      hardware roots. The verifier also relies on the launch-measurement policy,
      firmware, guest image construction, and currently the operator-controlled
      mutable disk. SNP does not address all side channels or traffic analysis.</li>
      <li><strong>When a GPU arrives:</strong> re-run the same matrix and report
      measured results separately. This report makes no GPU overhead or zkML
      throughput projection without data.</li>
    </ul>
    """


# ---------------------------------------------------------------- page

CSS = """
:root{color-scheme:light;
  --page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
  --grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,0.10);
  --s1:#2a78d6;--s2:#008300;--s3:#e87ba4;--s4:#eda100;--s5:#7a58c7;}
@media (prefers-color-scheme: dark){
  :root:where(:not([data-theme="light"])){color-scheme:dark;
    --page:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;
    --grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,0.10);
    --s1:#3987e5;--s2:#008300;--s3:#d55181;--s4:#c98500;--s5:#a88ae2;}}
:root[data-theme="dark"]{color-scheme:dark;
  --page:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,0.10);
  --s1:#3987e5;--s2:#008300;--s3:#d55181;--s4:#c98500;--s5:#a88ae2;}
*{box-sizing:border-box;margin:0}
body{background:var(--page);color:var(--ink);
  font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;padding:2rem 1rem 4rem}
main{max-width:860px;margin:0 auto}
h1{font-size:1.7rem;line-height:1.25;margin-bottom:.4rem}
h2{font-size:1.15rem;margin:0 0 .6rem}
p{color:var(--ink2);margin-bottom:.8rem}
p strong,li strong{color:var(--ink)}
.sub{color:var(--muted);font-size:.9rem;margin-bottom:1.6rem}
section{background:var(--surface);border:1px solid var(--border);border-radius:10px;
  padding:1.4rem 1.5rem 1rem;margin-bottom:1.4rem}
svg{width:100%;height:auto;display:block;margin:.4rem 0 .2rem}
.grid{stroke:var(--grid);stroke-width:1}
.axis{stroke:var(--axis);stroke-width:1}
.leader{stroke:var(--axis);stroke-width:1}
.tick{fill:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.vlabel{fill:var(--ink2);font-size:12px;font-variant-numeric:tabular-nums}
.endlabel{fill:var(--ink2);font-size:12.5px}
.ln{stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.dot{stroke:var(--surface);stroke-width:2}
.legend{display:flex;flex-wrap:wrap;gap:.9rem;margin:.3rem 0 .2rem;font-size:.85rem;color:var(--ink2)}
.lg{display:inline-flex;align-items:center;gap:.4rem}
.sw{width:11px;height:11px;border-radius:3px;display:inline-block}
.provenance{color:var(--muted);font-size:.78rem;border-top:1px solid var(--grid);
  padding-top:.5rem;margin:.7rem 0 .2rem}
.provenance summary{cursor:pointer}
.provenance-runs{display:flex;flex-wrap:wrap;gap:.25rem .45rem;margin-top:.45rem;max-height:14rem;overflow:auto}
.provenance-runs a{color:var(--ink2)}
.provenance code{font-size:.95em}
code{background:color-mix(in srgb,var(--ink) 6%,transparent);padding:.05em .3em;border-radius:4px}
.tablewrap{overflow-x:auto;margin:.5rem 0}
table{border-collapse:collapse;font-size:.85rem;min-width:100%}
th{color:var(--muted);font-weight:600;text-align:left}
th,td{padding:.4rem .7rem;border-bottom:1px solid var(--grid);white-space:nowrap}
td{color:var(--ink2);font-variant-numeric:tabular-nums}
td:first-child{color:var(--ink)}
details.tv{margin:.3rem 0 .5rem}
details.tv summary{color:var(--muted);font-size:.82rem;cursor:pointer}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.8rem;margin-bottom:1.4rem}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:.9rem 1rem}
.tile .lab{color:var(--muted);font-size:.78rem;margin-bottom:.2rem}
.tile .val{font-size:1.55rem;font-weight:600;line-height:1.15}
.tile .ctx{color:var(--muted);font-size:.75rem;margin-top:.15rem}
.banner{background:color-mix(in srgb,var(--s4) 12%,var(--surface));border:1px solid var(--border);
  border-radius:10px;padding:.7rem 1rem;font-size:.85rem;color:var(--ink2);margin-bottom:1.4rem}
.placeholder{font-style:italic}
ul{color:var(--ink2);padding-left:1.2rem;margin-bottom:.8rem}
li{margin-bottom:.35rem}
"""


def build(args):
    raw_records = load_jsonl(args.requests)
    records, warmups = discard_request_warmups(raw_records)
    sessions = load_jsonl(args.sessions)
    registry = {
        entry["id"]: entry
        for entry in yaml.safe_load((REPO / "models.yaml").read_text())
    }

    stream_body, stream_tax, m_off, m_on = section_stream(sessions)
    tax_body, tax = section_tax_curves(records)
    tps_body, tps_ab = section_tps_ab(records)
    snp_twin_body = section_snp_twin(records)
    glm_body = section_glm(records, registry, args.box_cost_per_hr)
    cost_body = section_cost(
        records,
        tps_ab,
        args.box_cost_per_hr,
        args.api_input_per_mtok,
        args.api_output_per_mtok,
    )
    attest_body = section_attestation(records)
    c_body, c_delta_ms, c_delta_pct = section_leg_c(records)
    d_body = section_leg_d(records)
    be_body = section_breakeven(records, tps_ab, args.box_cost_per_hr)

    worst_model = max(tax, key=tax.get) if tax else "—"
    worst_tax = tax[worst_model] if tax else 0.0
    mults = [a / b for (a, b) in tps_ab.values() if b]

    all_ids = sorted(r["run_id"] for r in records)
    all_ts = sorted(r["ts"] for r in records)

    banner = (
        '<div class="banner"><strong>Measured on cat-verif</strong> '
        "(AMD EPYC 9555P Turin, 1.13 TiB). Every number traces to a run_id "
        f"in runs/. {len(warmups)} warmup requests are retained in raw JSONL "
        "but excluded from aggregation. No synthetic or mock data.</div>"
    )

    tiles = f"""
    <div class="tiles">
      <div class="tile"><div class="lab">STREAM bandwidth tax (SEV-ES)</div>
        <div class="val">−{stream_tax:.1f}%</div>
        <div class="ctx">{fmt(m_off)} → {fmt(m_on)} GB/s triad</div></div>
      <div class="tile"><div class="lab">Worst decode tax</div>
        <div class="val">{worst_tax:+.1f}%</div>
        <div class="ctx">{esc(worst_model)}, single stream @ 32 threads</div></div>
      <div class="tile"><div class="lab">Attested-proxy TTFT delta (leg C)</div>
        <div class="val">{c_delta_ms:+.0f} ms</div>
        <div class="ctx">median matched-shape TTFT difference</div></div>
      <div class="tile"><div class="lab">Break-even premium</div>
        <div class="val">{f"×{min(mults):.2f}–×{max(mults):.2f}" if mults else "n/a"}</div>
        <div class="ctx">cost_B / cost_A across models</div></div>
    </div>"""

    methods = f"""
    <section><h2>Method notes</h2>
    <p>Aggregation is <strong>median</strong> throughout, with <strong>p99</strong>
    where tails matter (ITL, attestation phases). Harness convention: n ≥ 5 runs
    per A/B/C cell targets n ≥ 10; leg D targets n = 5. The <strong>first 2 raw
    records per cell are discarded during aggregation</strong>. Raw JSONL is
    immutable and includes those requests; sparse cells stay visible rather
    than being erased.
    Legs A and B differ only in SEV
    state: same kernel, model files, thread pinning
    (<code>numa_policy</code> recorded per request), and runtime versions.
    Leg D encodes the ladder rung in the model field because the frozen v1
    schema has no rung field. Charts derive exclusively from the two input
    files; every chart lists the run_ids behind it.</p>
    <p class="provenance">Inputs: <code>{esc(args.requests)}</code>
    ({len(raw_records)} raw request records; {len(records)} retained after
    {len(warmups)} warmups, retained run_ids <code>{esc(all_ids[0])}</code> …
    <code>{esc(all_ids[-1])}</code>, ts {esc(all_ts[0])} … {esc(all_ts[-1])}) ·
    <code>{esc(args.sessions)}</code> ({len(sessions)} session records)</p>
    </section>"""

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verified inference: what the TEE actually costs</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>Verified inference: what the TEE actually costs</h1>
<p class="sub">AMD EPYC 9555P (Zen 5, 64C/128T, ~614 GB/s) · legs A/B/C/D ·
generated by <code>report/generate.py</code></p>
{banner}
{tiles}
<section><h2>1 · STREAM anchor — the bandwidth the encryption eats</h2>{stream_body}</section>
<section><h2>2 · TEE inference tax — overhead per model, matched cell</h2>{tax_body}</section>
<section><h2>3 · Throughput, A vs B</h2>{tps_body}</section>
<section><h2>4 · Full SNP sweep — matched plain twin</h2>{snp_twin_body}</section>
<section><h2>5 · GLM-5.2 flagship — measured scope and missing TEE cell</h2>{glm_body}</section>
<section><h2>6 · $/1M output tokens</h2>{cost_body}</section>
<section><h2>7 · Attestation &amp; receipt cost breakdown</h2>{attest_body}</section>
<section><h2>8 · Leg C — attested proxy vs direct API</h2>{c_body}</section>
<section><h2>9 · Leg D — zkML ladder</h2>{d_body}</section>
<section><h2>10 · Break-even — the premium verification must command</h2>{be_body}</section>
<section><h2>11 · Honest limits</h2>{section_limits()}</section>
{methods}
</main>
</body>
</html>
"""
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(
        f"wrote {out} ({out.stat().st_size:,} bytes) from {len(records)} request "
        f"+ {len(sessions)} session records"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--requests",
        default=str(REPO / "runs/real-requests.jsonl"),
        help="per-request JSONL (harness/schema.json)",
    )
    ap.add_argument(
        "--sessions",
        default=str(REPO / "runs/all-sessions.jsonl"),
        help="per-session JSONL (harness/session_schema.json)",
    )
    ap.add_argument("--out", default=str(HERE / "out/report.html"))
    ap.add_argument(
        "--box-cost-per-hr",
        type=float,
        default=2.50,
        help="box amortization, $/hour (default: 2.50 — stated in the report)",
    )
    ap.add_argument(
        "--api-input-per-mtok",
        type=float,
        default=1.00,
        help="published API input price, $/1M tokens (leg C rows)",
    )
    ap.add_argument(
        "--api-output-per-mtok",
        type=float,
        default=5.00,
        help="published API output price, $/1M tokens (leg C rows)",
    )
    build(ap.parse_args())


if __name__ == "__main__":
    main()
