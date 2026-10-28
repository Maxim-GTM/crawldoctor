import type { ReactNode } from "react"
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react"

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

/** KPI tile: icon + label, the number, its change against the previous period, and one line of context. */
export function StatCard({ icon, label, value, hint, delta, loading, className }: {
  icon: ReactNode; label: string; value: ReactNode; hint?: ReactNode; delta?: ReactNode; loading?: boolean; className?: string
}) {
  return (
    <Card className={cn("gap-2 py-4", className)}>
      <CardHeader className="gap-1.5 px-4">
        <CardDescription className="flex items-center gap-2 [&_svg]:size-4">{icon}{label}</CardDescription>
        {loading ? <Skeleton className="h-8 w-24" /> : (
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <CardTitle className="text-2xl font-semibold tabular-nums">{value}</CardTitle>
            {delta}
          </div>
        )}
        <div className="min-h-4 truncate text-xs text-muted-foreground">{loading ? <Skeleton className="h-3 w-28" /> : hint}</div>
      </CardHeader>
    </Card>
  )
}

/**
 * "↑ 12%" against the previous period. `points` compares percentages in percentage points;
 * `neutral` drops the good/bad colouring for numbers where up isn't better (bot traffic).
 */
export function Delta({ current, previous, points, neutral, period }: {
  current: number; previous: number | undefined; points?: boolean; neutral?: boolean; period: string
}) {
  if (previous === undefined) return <Skeleton className="h-4 w-12 self-center" />
  const diff = current - previous
  let text: string
  if (points) text = `${Math.abs(diff).toFixed(1)} pts`
  else if (!previous) text = current ? "new" : "0%"
  else {
    const p = Math.abs(diff / previous) * 100
    text = `${p < 10 && p > 0 ? p.toFixed(1) : Math.round(p)}%`
  }
  const flat = points ? Math.abs(diff) < 0.05 : !diff
  const Icon = flat ? Minus : diff > 0 ? ArrowUpRight : ArrowDownRight
  const tone = flat || neutral ? "text-muted-foreground" : diff > 0 ? "text-good" : "text-destructive"
  return (
    <span className={cn("inline-flex items-center gap-0.5 text-xs font-medium tabular-nums", tone)}
      title={`${points ? previous.toFixed(1) + "%" : previous.toLocaleString()} in the previous ${period}`}>
      <Icon className="size-3.5" />{text}
    </span>
  )
}
