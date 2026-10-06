type N = number | null | undefined;

const isNum = (v: N): v is number => typeof v === "number" && Number.isFinite(v);

export function fmtMoney(v: N, digits = 2): string {
  if (!isNum(v)) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** 3.9e12 -> "3.90T", -2.1e9 -> "-2.10B" */
export function fmtBig(v: N, digits = 2): string {
  if (!isNum(v)) return "—";
  const a = Math.abs(v);
  const [d, s] =
    a >= 1e12 ? [1e12, "T"] : a >= 1e9 ? [1e9, "B"] : a >= 1e6 ? [1e6, "M"] : a >= 1e3 ? [1e3, "K"] : [1, ""];
  return `${(v / d).toFixed(digits)}${s}`;
}

/** fraction -> percent string: 0.123 -> "12.3%" */
export function fmtPct(v: N, digits = 1, signed = false): string {
  if (!isNum(v)) return "—";
  const s = (v * 100).toFixed(digits);
  return `${signed && v > 0 ? "+" : ""}${s}%`;
}

export function fmtNum(v: N, digits = 2, suffix = ""): string {
  if (!isNum(v)) return "—";
  return `${v.toFixed(digits)}${suffix}`;
}

/** Valuation multiple: <=0 or >500 is not meaningful (near-zero earnings, data errors). */
export function fmtMult(v: N, digits = 1): string {
  if (!isNum(v)) return "—";
  return v <= 0 || v > 500 ? "n/m" : v.toFixed(digits);
}

export function toneClass(v: N): string {
  if (!isNum(v) || v === 0) return "text-on-surface-muted";
  return v > 0 ? "text-primary" : "text-tertiary";
}

export function median(xs: N[]): number | null {
  const a = xs.filter(isNum).sort((x, y) => x - y);
  if (!a.length) return null;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export { isNum };
