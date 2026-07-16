// Formatting rules: only render what the API returned. Anything absent is "—".

export const DASH = "—";

export function trunc(hex: string | null | undefined, n = 6): string {
  if (!hex) return DASH;
  return hex.length <= 2 * n + 1 ? hex : `${hex.slice(0, n)}…${hex.slice(-n)}`;
}

/** Millisecond value split for meter display: {value, unit}. */
export function msParts(v: number | null | undefined): { value: string; unit: string } {
  if (v == null || Number.isNaN(v)) return { value: DASH, unit: "" };
  if (v >= 10_000) return { value: (v / 1000).toFixed(2), unit: "s" };
  return { value: v >= 100 ? v.toFixed(0) : v.toFixed(1), unit: "ms" };
}

export function fmtMs(v: number | null | undefined): string {
  const { value, unit } = msParts(v);
  return unit ? `${value} ${unit}` : value;
}

export function fmtRate(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return v >= 100 ? v.toFixed(0) : v.toFixed(1);
}

export function fmtUsdc(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return v.toFixed(6);
}

export function fmtPrice(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return v.toFixed(2);
}

export function fmtInt(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return v.toLocaleString("en-US");
}

export function fmtClock(tsMs: number): string {
  const d = new Date(tsMs);
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
