export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return iso
  const s = Math.round((Date.now() - t) / 1000)
  if (s < 45) return "just now"
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  if (s < 86400 * 7) return `${Math.round(s / 86400)} d ago`
  return shortDate(iso)
}

export function fullTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
}

export function clockTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

/** Seconds as "42s", "3.5 min", "2.1 h" or "4.2 d". */
export function seconds(s: number | null | undefined): string {
  if (s === null || s === undefined || Number.isNaN(s)) return "—"
  if (s < 90) return `${Math.round(s)}s`
  if (s < 5400) return `${(s / 60).toFixed(s < 600 ? 1 : 0)} min`
  if (s < 172800) return `${(s / 3600).toFixed(1)} h`
  return `${(s / 86400).toFixed(1)} d`
}

export const num = (n: number | null | undefined) => (n ?? 0).toLocaleString()

export function pct(part: number, whole: number, digits = 1): string {
  if (!whole) return "0%"
  const v = (part / whole) * 100
  return `${v < 10 && v > 0 ? v.toFixed(digits) : Math.round(v)}%`
}

export const plural = (n: number, one: string, many = `${one}s`) => `${num(n)} ${n === 1 ? one : many}`

/** Splits a URL into its host and path, so tables can show the path and mute the host. */
export function splitUrl(url: string | null | undefined): { host: string; path: string } {
  if (!url) return { host: "", path: "" }
  try {
    const u = new URL(url)
    return { host: u.host, path: `${u.pathname}${u.search}` || "/" }
  } catch {
    return { host: "", path: url }
  }
}

export const stripOrigin = (url: string | null | undefined) => (url ? url.replace(/^https?:\/\/[^/]+/, "") || "/" : "")

export function place(city?: string | null, country?: string | null): string {
  return [city, country].filter(Boolean).join(", ")
}

/** "form_submit" → "Form submit" */
export function humanize(s: string | null | undefined): string {
  if (!s) return ""
  const t = s.replace(/[_-]+/g, " ").trim()
  return t.charAt(0).toUpperCase() + t.slice(1)
}

/* ---------- Date ranges (YYYY-MM-DD in UTC, as the API reads them) ---------- */

export const isoDay = (d: Date) => d.toISOString().slice(0, 10)

export function daysAgo(n: number): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() - n)
  return isoDay(d)
}

export function rangeLabel(start: string, end: string): string {
  const fmt = (s: string, withYear: boolean) =>
    new Date(`${s}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: withYear ? "numeric" : undefined, timeZone: "UTC" })
  const sameYear = start.slice(0, 4) === end.slice(0, 4)
  return start === end ? fmt(start, true) : `${fmt(start, !sameYear)} – ${fmt(end, true)}`
}

const DAY_MS = 86_400_000

/** Days in a range, both ends included. */
export const rangeDays = (r: { start: string; end: string }) =>
  Math.round((Date.parse(`${r.end}T00:00:00Z`) - Date.parse(`${r.start}T00:00:00Z`)) / DAY_MS) + 1

/** The same number of days just before the range, to compare against. */
export function previousRange(r: { start: string; end: string }): { start: string; end: string } {
  const n = rangeDays(r)
  const start = Date.parse(`${r.start}T00:00:00Z`)
  return { start: isoDay(new Date(start - n * DAY_MS)), end: isoDay(new Date(start - DAY_MS)) }
}

/** Every UTC day in the range, oldest first. */
export function eachDay(r: { start: string; end: string }): string[] {
  const out: string[] = []
  for (let t = Date.parse(`${r.start}T00:00:00Z`), end = Date.parse(`${r.end}T00:00:00Z`); t <= end; t += DAY_MS) out.push(isoDay(new Date(t)))
  return out
}

/** "Oct 3" for a YYYY-MM-DD day. */
export const dayLabel = (day: string) =>
  new Date(`${day}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" })
