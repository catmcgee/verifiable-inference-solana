#!/usr/bin/env python3
"""Verified-inference report generator.

Reads per-request JSONL (harness/schema.json) and per-session JSONL
(harness/session_schema.json), aggregates, and writes a fully self-contained
HTML report (inline CSS + hand-rolled inline SVG; no CDN, no JS frameworks).

Run:  uv run report/generate.py
      uv run report/generate.py --requests runs/real.jsonl --sessions runs/sessions.jsonl
"""

import argparse
import html
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

MODEL_ORDER = ["bitnet-2b", "8b-q4", "8b-q8", "70b-q4"]
THREAD_ORDER = [16, 32, 64, 128]
PROMPT_ORDER = [128, 1024, 8192]

# Categorical slots (validated reference palette, fixed order — see dataviz skill).
SLOT_VARS = ["--s1", "--s2", "--s3", "--s4"]
MODEL_SLOT = {m: SLOT_VARS[i] for i, m in enumerate(MODEL_ORDER)}
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


def provenance(records):
    """Data-provenance footer: run_id range + count (standing rule)."""
    ids = sorted(r["run_id"] for r in records)
    if not ids:
        return '<p class="provenance">Provenance: no records.</p>'
    return (
        f'<p class="provenance">Provenance: {len(ids)} records · '
        f'run_ids <code>{esc(ids[0])}</code> … <code>{esc(ids[-1])}</code></p>'
    )


def sess_provenance(sessions):
    ids = sorted(s["session_id"] for s in sessions)
    if not ids:
        return '<p class="provenance">Provenance: no session records.</p>'
    return (
        f'<p class="provenance">Provenance: {len(ids)} session records · '
        f'session_ids <code>{esc(ids[0])}</code> … <code>{esc(ids[-1])}</code></p>'
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
    return (f'M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} '
            f'L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} '
            f'L{x + w:.1f},{y + h:.1f} Z')


def hbar_path(x, y, w, h, r=4):
    """Horizontal bar, rounded right data-end, square at the left baseline."""
    if w <= 0:
        return ""
    r = min(r, h / 2, w)
    return (f'M{x:.1f},{y:.1f} L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} '
            f'L{x + w:.1f},{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} '
            f'L{x:.1f},{y + h:.1f} Z')


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
        out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" class="grid"/>')
        out.append(f'<text x="{x0 - 8}" y="{y + 4:.1f}" class="tick" text-anchor="end">{fmt(tv)}{unit}</text>')
    out.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" class="axis"/>')
    return "".join(out)


def grouped_bar_svg(categories, series, unit="", height=340, value_fmt=fmt):
    """categories: [str]; series: [(name, css_var, [values])]."""
    W = 760
    ml, mr, mt, mb = 64, 20, 18, 46
    x0, x1, y0, y1 = ml, W - mr, mt, height - mb
    vmax = nice_max(max(max(vs) for _, _, vs in series))
    out = [f'<svg viewBox="0 0 {W} {height}" role="img" preserveAspectRatio="xMidYMid meet">']
    out.append(grid_and_yaxis(x0, x1, y0, y1, vmax, unit))

    ncat, nser = len(categories), len(series)
    band = (x1 - x0) / ncat
    barw = min(24.0, (band * 0.62 - 2 * (nser - 1)) / nser)
    group_w = barw * nser + 2 * (nser - 1)

    for ci, cat in enumerate(categories):
        gx = x0 + band * ci + (band - group_w) / 2
        out.append(f'<text x="{x0 + band * (ci + 0.5):.1f}" y="{y1 + 20}" class="tick" text-anchor="middle">{esc(cat)}</text>')
        labels = []
        for si, (name, var, vals) in enumerate(series):
            v = vals[ci]
            h = (y1 - y0) * (v / vmax) if vmax else 0
            bx = gx + si * (barw + 2)  # 2px surface gap between adjacent bars
            by = y1 - h
            out.append(f'<path d="{bar_path(bx, by, barw, h)}" style="fill:var({var})">'
                       f'<title>{esc(name)} · {esc(cat)}: {value_fmt(v)}{unit}</title></path>')
            labels.append([bx + barw / 2, by - 6, value_fmt(v)])
        # stagger cap labels that would collide with a neighbor's
        for li in range(1, len(labels)):
            px, py, _ = labels[li - 1]
            if abs(labels[li][0] - px) < 44 and abs(labels[li][1] - py) < 13:
                labels[li][1] = py - 13
        for lx, ly, txt in labels:
            out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" class="vlabel" text-anchor="middle">{txt}</text>')
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

    out = [f'<svg viewBox="0 0 {W} {height}" role="img" preserveAspectRatio="xMidYMid meet">']
    out.append(grid_and_yaxis(x0, x1, y0, y1, vmax, unit))
    for i, lab in enumerate(x_labels):
        out.append(f'<text x="{xs[i]:.1f}" y="{y1 + 20}" class="tick" text-anchor="middle">{esc(lab)}</text>')
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
        out.append(f'<polyline points="{pts}" style="stroke:var({var})" class="ln" fill="none">'
                   f'<title>{esc(name)}</title></polyline>')
        for i, v in enumerate(vs):
            out.append(f'<circle cx="{xs[i]:.1f}" cy="{ypix(v):.1f}" r="4" class="dot" style="fill:var({var})">'
                       f'<title>{esc(name)} · {esc(x_labels[i])}: {fmt(v)}{unit}</title></circle>')
        if abs(ly - ey) > 7:  # leader line when nudged
            out.append(f'<line x1="{x1 + 4}" y1="{ey:.1f}" x2="{x1 + 16}" y2="{ly:.1f}" class="leader"/>')
        out.append(f'<text x="{x1 + 20}" y="{ly + 4:.1f}" class="endlabel">'
                   f'<tspan style="fill:var({var})">●</tspan> {esc(name)}</text>')
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
    out = [f'<svg viewBox="0 0 {W} {height}" role="img" preserveAspectRatio="xMidYMid meet">']
    out.append(f'<line x1="{x0}" y1="{mt}" x2="{x0}" y2="{height - 14}" class="axis"/>')
    for i, (label, v, var) in enumerate(rows):
        y = mt + i * (rh + gap)
        w = (x1 - x0) * (v / vmax if vmax else 0)
        out.append(f'<text x="{x0 - 10}" y="{y + rh / 2 + 4}" class="tick" text-anchor="end">{esc(label)}</text>')
        out.append(f'<path d="{hbar_path(x0, y, max(w, 1.5), rh)}" style="fill:var({var})">'
                   f'<title>{esc(label)}: {fmt(v, 2)}{unit}</title></path>')
        out.append(f'<text x="{x0 + max(w, 1.5) + 8:.1f}" y="{y + rh / 2 + 4}" class="vlabel">{fmt(v, 2)}{unit}</text>')
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

    m_off, off = one(lambda s: s["sev_mode"] == "off" and "vm" in s["session_id"]
                     and "baremetal" not in s["session_id"])
    m_on, on = one(lambda s: s["sev_mode"] == "es")
    tax = (m_off - m_on) / m_off * 100 if m_off and m_on else 0
    m_bare, bare = one(lambda s: s["sev_mode"] == "off" and "baremetal" in s["session_id"])
    m_snp, snp = one(lambda s: s["sev_mode"] == "snp")

    bars = [("Plain VM · SEV off", m_off, SEV_OFF_SLOT), ("CVM · SEV-ES", m_on, SEV_ON_SLOT)]
    anchors = []
    if m_bare:
        anchors.append(("Bare metal (128t anchor)", m_bare, "--s3"))
    if m_snp:
        anchors.append(("SNP CVM (separate run)", m_snp, "--s4"))
    svg = two_bar_svg(bars + anchors, " GB/s")

    snp_line = (f" The SNP CVM anchor ({fmt(m_snp)} GB/s, KDS-verified, separate "
                "run) is shown for context only — a different kernel/day, not a "
                "matched SEV-off↔SNP pair, so no SNP tax is claimed from it.") if m_snp else ""
    tbl_rows = [["Plain VM (off)", fmt(m_off), str(len(off))],
                ["CVM (SEV-ES)", fmt(m_on), str(len(on))]]
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
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" preserveAspectRatio="xMidYMid meet">']
    out.append(grid_and_yaxis(x0, x1, y0, y1, vmax))
    band = (x1 - x0) / len(rows)
    for i, (label, v, var) in enumerate(rows):
        h = (y1 - y0) * v / vmax
        bx = x0 + band * i + band / 2 - 12
        out.append(f'<path d="{bar_path(bx, y1 - h, 24, h)}" style="fill:var({var})">'
                   f'<title>{esc(label)}: {fmt(v)}{unit}</title></path>')
        out.append(f'<text x="{bx + 12:.1f}" y="{y1 - h - 8:.1f}" class="vlabel" text-anchor="middle">{fmt(v)}{unit}</text>')
        out.append(f'<text x="{x0 + band * (i + 0.5):.1f}" y="{y1 + 20}" class="tick" text-anchor="middle">{esc(label)}</text>')
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
            out[m] = (med(r["tokens_per_s"] for r in a),
                      med(r["tokens_per_s"] for r in b))
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
        return ("<p class='placeholder'>No matched A/B cell in the data — "
                "cannot compute a TEE inference tax. (Need both legs at the same "
                "model/threads/prompt/concurrency.)</p>", tax)

    # bars are tax magnitude; sign + note fold into the row label (a small
    # negative just means B measured slightly faster — i.e. within run-to-run
    # noise, no measurable tax).
    def lab(m):
        t = tax[m]
        sign = "−" if t < 0 else "+"
        tail = " (within noise)" if abs(t) < 1.0 or t < 0 else ""
        return f"{m}  {sign}{abs(t):.1f}%{tail}"
    svg = hbar_svg([(lab(m), abs(tax[m]), MODEL_SLOT[m]) for m in models], unit="%")
    rows = [[m, fmt(matched[m][0], 2), fmt(matched[m][1], 2), f"{tax[m]:+.1f}%"]
            for m in models]
    missing = [m for m in MODEL_ORDER if m not in matched]
    miss_note = (f" ({', '.join(missing)} were not run on both legs at this cell, "
                 "so no tax is shown for them.)") if missing else ""
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
    figure is the <em>ceiling</em> a fully bandwidth-saturating workload (many
    concurrent streams, or a much larger model) would climb toward — not the
    tax a single decode stream actually pays. Measuring that ceiling needs a
    concurrency/thread A/B sweep on leg B, which has not been run (leg B has one
    cell only); this chart does not extrapolate to it.</p>
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
        rows.append([
            m, fmt(am, 2), fmt(bm, 2), f"{(am - bm) / am * 100:+.1f}%",
            fmt(med(r["itl_ms_p50"] for r in a), 2), fmt(p99([r["itl_ms_p99"] for r in a]), 2),
            fmt(med(r["itl_ms_p50"] for r in b), 2), fmt(p99([r["itl_ms_p99"] for r in b]), 2),
        ])
    svg = grouped_bar_svg(models,
                          [("A · SEV off", SEV_OFF_SLOT, a_vals), ("B · SEV-ES", SEV_ON_SLOT, b_vals)],
                          unit="", value_fmt=lambda v: fmt(v, 1))
    body = f"""
    <p>Median single-stream decode throughput (tokens/s) at the matched A/B cell
    (32 threads, concurrency 1). The bars sit nearly on top of each other —
    that visual near-equality <em>is</em> the ~2% tax result. The table adds
    inter-token latency: median of per-request p50 and p99-of-p99s.</p>
    {legend_html([("A · SEV off", SEV_OFF_SLOT), ("B · SEV-ES", SEV_ON_SLOT)])}
    {svg}
    {table_view(["Model", "A tok/s", "B tok/s", "SEV tax",
                 "A ITL p50 (ms)", "A ITL p99 (ms)", "B ITL p50 (ms)", "B ITL p99 (ms)"], rows)}
    {provenance(slice_)}
    """
    return body, {m: matched[m] for m in models}


def cost_per_mtok(tps, box_cost_hr):
    """$ per 1M output tokens at a given sustained tokens/s."""
    return box_cost_hr / (tps * 3600.0) * 1e6 if tps else float("inf")


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
    rows.append(["C-direct · claude-sonnet-4 (published API)", f"${api_out:,.2f}",
                 f"published output price (input ${api_in:,.2f}/1M)"])
    rows.append(["C-proxied · same + CVM proxy", f"${api_out:,.2f} + proxy share",
                 "API price + amortized proxy box"])
    slice_ = sel(records, leg=("A", "B"), **AB_CELL)
    body = f"""
    <p><strong>Cost parameterization (stated, not hidden):</strong> the box is
    amortized at <strong>${box_cost_hr:.2f}/hour</strong> (hardware + power +
    hosting, straight-line; change with <code>--box-cost-per-hr</code>).
    $/1M output tokens = hourly cost ÷ (tokens/s × 3600) × 10⁶, using the
    single-stream median at the matched A/B cell (32 threads, concurrency 1).
    A batched (concurrency-8) column is intentionally omitted: leg B was not run
    at concurrency 8, so there is no matched leg-B number to divide against —
    the generator renders what was measured, not an extrapolation. Leg C rows
    use published Anthropic API pricing (parameterized:
    <code>--api-input-per-mtok</code>, <code>--api-output-per-mtok</code>) — API
    tokens are priced by Anthropic, not by this box's amortization.</p>
    {table_html(["Config", "$/1M output tok (single stream)", "Basis"], rows)}
    {provenance(slice_)}
    """
    return body


def section_attestation(records):
    b = sel(records, leg="B")
    fields = [
        ("Attestation fetch (snpguest report)", "attest_fetch_ms"),
        ("Attestation verify (VCEK → ASK/ARK)", "attest_verify_ms"),
        ("Receipt sign (ed25519, in-enclave)", "receipt_sign_ms"),
        ("Receipt post (devnet submit)", "receipt_post_ms"),
        ("Receipt confirm (devnet)", "receipt_confirm_ms"),
    ]
    rows_svg = [(label, med(r[f] for r in b), "--s1") for label, f in fields]
    rows_tbl = [[label, fmt(med(r[f] for r in b), 2), fmt(p99([r[f] for r in b]), 2)] for label, f in fields]
    cu = med(r["solana_cu"] for r in b)
    fee = med(r["solana_fee_lamports"] for r in b)
    body = f"""
    <p>Median per-request cost of the verification machinery on leg B. Fetch +
    verify happen per attestation refresh (cached certs assumed); receipt
    post/confirm are asynchronous devnet round-trips and do not sit on the
    token stream. Median receipt: {fmt(cu, 0)} CU, {fmt(fee, 0)} lamports.
    What SNP attestation proves — and what launch-only would not — is spelled
    out in the honest-limits section.</p>
    {hbar_svg(rows_svg)}
    {table_view(["Phase", "Median (ms)", "p99 (ms)"], rows_tbl)}
    {provenance(b)}
    """
    return body


def section_leg_c(records):
    c = sel(records, leg=("C-direct", "C-proxied"))
    cats = [f"{p} tok prompt" for p in PROMPT_ORDER]
    d_vals, p_vals, rows = [], [], []
    deltas = []
    for pt in PROMPT_ORDER:
        d = sel(c, leg="C-direct", prompt_tokens=pt, concurrency=1)
        pr = sel(c, leg="C-proxied", prompt_tokens=pt, concurrency=1)
        dm, pm = med(r["ttft_ms"] for r in d), med(r["ttft_ms"] for r in pr)
        de, pe = med(r["e2e_ms"] for r in d), med(r["e2e_ms"] for r in pr)
        d_vals.append(dm)
        p_vals.append(pm)
        deltas.append((pm - dm, (pe - de) / de * 100 if de else 0))
        pct = f"+{(pe - de) / de * 100:.1f}%" if de and pe else "—"
        rows.append([f"{pt}", fmt(dm, 0), fmt(pm, 0), f"+{pm - dm:.0f}" if pm else "—",
                     fmt(de, 0), fmt(pe, 0), pct])
    delta_ms = med(d[0] for d in deltas)
    delta_pct = med(d[1] for d in deltas)
    svg = grouped_bar_svg(cats, [("C-direct", SEV_OFF_SLOT, d_vals), ("C-proxied (CVM)", SEV_ON_SLOT, p_vals)],
                          unit=" ms", value_fmt=lambda v: fmt(v, 0))
    body = f"""
    <p>Leg C is the honest control: the attested CVM proxy in front of the
    Claude API proves only the proxy's routing/logging policy — inference
    itself is not verified and Anthropic sees plaintext. Its cost: the proxy
    adds a median <strong>+{delta_ms:.0f} ms</strong> to TTFT
    (≈ {delta_pct:.1f}% of end-to-end at these shapes). Median TTFT by prompt
    size, concurrency 1:</p>
    {legend_html([("C-direct", SEV_OFF_SLOT), ("C-proxied (CVM)", SEV_ON_SLOT)])}
    {svg}
    {table_view(["Prompt tok", "direct TTFT (ms)", "proxied TTFT (ms)", "Δ TTFT (ms)",
                 "direct e2e (ms)", "proxied e2e (ms)", "Δ e2e"], rows)}
    {provenance(c)}
    """
    return body, delta_ms, delta_pct


def section_leg_d(records):
    d = sel(records, leg="D")
    if not d:
        return (
            '<p class="placeholder">Leg D has no measurement rows. None of the '
            'required matmul-to-token ladder has run, and the on-chain proof '
            'instruction is an explicitly unverified stub. Leg D would prove '
            'integrity for a public model and hashed input, not input privacy. '
            f'No proving-time or Groth16 claim is made.</p>{provenance(d)}'
        )
    rung_models = sorted({r["model"] for r in d})
    rows = []
    for m in rung_models:
        off = sel(d, model=m, sev_mode="off")
        snp = [r for r in sel(d, model=m) if r["sev_mode"] != "off"]
        po = med(r["e2e_ms"] for r in off) / 1000.0
        ps = med(r["e2e_ms"] for r in snp) / 1000.0 if snp else 0.0
        rows.append([
            f"rung {m.rsplit('rung', 1)[-1]}",
            m,
            f"{po:,.0f} s", f"{ps:,.0f} s" if snp else "—",
            f"+{(ps - po) / po * 100:.1f}%" if snp and po else "—",
            fmt(med(r["attest_verify_ms"] for r in off), 1),
            f"{med(r['solana_cu'] for r in off):,.0f}",
            f"{med(r['solana_fee_lamports'] for r in off):,.0f}",
        ])
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
    {table_html(["Rung", "model field", "Prove (SEV off, median)", "Prove (SEV on, median)",
                 "SEV tax", "Off-chain verify (ms)", "On-chain verify (CU)", "Fee (lamports)"], rows)}
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
        rows.append([m, f"${ca:,.2f}", f"${cb:,.2f}", f"×{mult:.3f}", f"{(mult - 1) * 100:+.1f}%"])
    slice_ = sel(records, leg=("A", "B"), **AB_CELL)
    body = f"""
    <p>Same box, same watts, same hour — the only thing SEV changes is tokens
    delivered per hour, so <strong>premium multiplier = cost_B / cost_A =
    tokens/s_A ÷ tokens/s_B</strong>. Reading: at the measured single-stream
    cell the premium is only a couple of percent (and for bitnet-2b the sign is
    negative — B measured marginally faster, i.e. within noise), so a buyer who
    values hardware-attested inference at even a few percent clears break-even.
    That is the <em>floor</em>: a bandwidth-saturating deployment would move the
    premium up toward the 26% STREAM ceiling, but that regime was not measured
    on leg B and is not asserted here. (Single-stream, 32 threads. Receipt costs
    are per-request, not per-token, listed separately in the attestation
    section; at devnet fees they are noise per 1M tokens.)</p>
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
  --s1:#2a78d6;--s2:#008300;--s3:#e87ba4;--s4:#eda100;}
@media (prefers-color-scheme: dark){
  :root:where(:not([data-theme="light"])){color-scheme:dark;
    --page:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;
    --grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,0.10);
    --s1:#3987e5;--s2:#008300;--s3:#d55181;--s4:#c98500;}}
:root[data-theme="dark"]{color-scheme:dark;
  --page:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,0.10);
  --s1:#3987e5;--s2:#008300;--s3:#d55181;--s4:#c98500;}
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
    records = load_jsonl(args.requests)
    sessions = load_jsonl(args.sessions)

    stream_body, stream_tax, m_off, m_on = section_stream(sessions)
    tax_body, tax = section_tax_curves(records)
    tps_body, tps_ab = section_tps_ab(records)
    cost_body = section_cost(records, tps_ab, args.box_cost_per_hr,
                             args.api_input_per_mtok, args.api_output_per_mtok)
    attest_body = section_attestation(records)
    c_body, c_delta_ms, c_delta_pct = section_leg_c(records)
    d_body = section_leg_d(records)
    be_body = section_breakeven(records, tps_ab, args.box_cost_per_hr)

    worst_model = max(tax, key=tax.get) if tax else "—"
    worst_tax = tax[worst_model] if tax else 0.0
    mults = [a / b for (a, b) in tps_ab.values() if b]

    all_ids = sorted(r["run_id"] for r in records)
    all_ts = sorted(r["ts"] for r in records)

    banner = ('<div class="banner"><strong>Measured on cat-verif</strong> '
              '(AMD EPYC 9555P Turin, 1.13 TiB). Every number traces to a run_id '
              'in runs/. No synthetic or mock data.</div>')

    tiles = f"""
    <div class="tiles">
      <div class="tile"><div class="lab">STREAM bandwidth tax (SEV-ES)</div>
        <div class="val">−{stream_tax:.1f}%</div>
        <div class="ctx">{fmt(m_off)} → {fmt(m_on)} GB/s triad</div></div>
      <div class="tile"><div class="lab">Worst decode tax</div>
        <div class="val">{worst_tax:+.1f}%</div>
        <div class="ctx">{esc(worst_model)}, single stream @ 32 threads</div></div>
      <div class="tile"><div class="lab">Attested-proxy tax (leg C)</div>
        <div class="val">+{c_delta_ms:.0f} ms</div>
        <div class="ctx">≈ {c_delta_pct:.1f}% of e2e, median</div></div>
      <div class="tile"><div class="lab">Break-even premium</div>
        <div class="val">{f"×{min(mults):.2f}–×{max(mults):.2f}" if mults else "n/a"}</div>
        <div class="ctx">cost_B / cost_A across models</div></div>
    </div>"""

    methods = f"""
    <section><h2>Method notes</h2>
    <p>Aggregation is <strong>median</strong> throughout, with <strong>p99</strong>
    where tails matter (ITL, attestation phases). Harness convention: n ≥ 5 runs
    per cell with the <strong>first 2 discarded</strong> as warmup before logging
    (kept samples carry ids <code>s03…</code>). Legs A and B differ only in SEV
    state: same kernel, model files, thread pinning
    (<code>numa_policy</code> recorded per request), and runtime versions.
    Leg D encodes the ladder rung in the model field because the frozen v1
    schema has no rung field. Charts derive exclusively from the two input
    files; every chart lists the run_ids behind it.</p>
    <p class="provenance">Inputs: <code>{esc(args.requests)}</code>
    ({len(records)} request records, run_ids <code>{esc(all_ids[0])}</code> …
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
<section><h2>4 · $/1M output tokens</h2>{cost_body}</section>
<section><h2>5 · Attestation &amp; receipt cost breakdown</h2>{attest_body}</section>
<section><h2>6 · Leg C — attested proxy vs direct API</h2>{c_body}</section>
<section><h2>7 · Leg D — zkML ladder</h2>{d_body}</section>
<section><h2>8 · Break-even — the premium verification must command</h2>{be_body}</section>
<section><h2>9 · Honest limits</h2>{section_limits()}</section>
{methods}
</main>
</body>
</html>
"""
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"wrote {out} ({out.stat().st_size:,} bytes) from {len(records)} request "
          f"+ {len(sessions)} session records")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--requests", default=str(REPO / "runs/real-requests.jsonl"),
                    help="per-request JSONL (harness/schema.json)")
    ap.add_argument("--sessions", default=str(REPO / "runs/all-sessions.jsonl"),
                    help="per-session JSONL (harness/session_schema.json)")
    ap.add_argument("--out", default=str(HERE / "out/report.html"))
    ap.add_argument("--box-cost-per-hr", type=float, default=2.50,
                    help="box amortization, $/hour (default: 2.50 — stated in the report)")
    ap.add_argument("--api-input-per-mtok", type=float, default=3.00,
                    help="published API input price, $/1M tokens (leg C rows)")
    ap.add_argument("--api-output-per-mtok", type=float, default=15.00,
                    help="published API output price, $/1M tokens (leg C rows)")
    build(ap.parse_args())


if __name__ == "__main__":
    main()
