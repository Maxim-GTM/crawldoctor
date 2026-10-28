import type { ReactNode } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { num, pct } from "@/lib/format"

export type BarRow = { key: string; label: ReactNode; value: number; color?: string; detail?: ReactNode }

/**
 * Ranked list with a proportional bar behind each row: easier to read than a pie for long labels.
 * Bars are scaled to the largest row; the share column is of `total` (defaults to the sum).
 */
export function BarList({ rows, total, loading, empty = "No data for this range.", showShare = true }: {
  rows: BarRow[]; total?: number; loading?: boolean; empty?: string; showShare?: boolean
}) {
  if (loading) return <div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-7" />)}</div>
  if (!rows.length) return <p className="py-6 text-center text-sm text-muted-foreground">{empty}</p>
  const max = Math.max(...rows.map((r) => r.value), 1)
  const sum = total ?? rows.reduce((a, r) => a + r.value, 0)

  return (
    <ul className="space-y-1">
      {rows.map((r) => (
        <li key={r.key} className="relative flex h-7 items-center gap-3 overflow-hidden rounded-md px-2 text-sm">
          <span aria-hidden className="absolute inset-y-0 left-0 rounded-md opacity-15"
            style={{ width: `${Math.max(1.5, (r.value / max) * 100)}%`, background: r.color ?? "var(--series-1)" }} />
          <span className="relative min-w-0 flex-1 truncate">{r.label}</span>
          {r.detail && <span className="relative hidden text-xs text-muted-foreground tabular-nums sm:inline">{r.detail}</span>}
          <span className="relative font-medium tabular-nums">{num(r.value)}</span>
          {showShare && <span className="relative w-11 text-right text-xs text-muted-foreground tabular-nums">{pct(r.value, sum)}</span>}
        </li>
      ))}
    </ul>
  )
}
