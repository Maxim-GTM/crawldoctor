import { ArrowDown } from "lucide-react"

import type { Funnel } from "@/lib/api"
import { num, pct } from "@/lib/format"

/** Overall conversion: last stage over first. */
export function funnelRate(f: Funnel): number {
  const first = f.stages[0]?.count ?? 0
  const last = f.stages[f.stages.length - 1]?.count ?? 0
  return first ? (last / first) * 100 : 0
}

/**
 * Stages as bars scaled to the first stage, with the step-to-step rate and drop-off between them.
 * `compact` leaves out the between-step rows (for the overview).
 */
export function FunnelSteps({ funnel, compact }: { funnel: Funnel; compact?: boolean }) {
  const first = funnel.stages[0]?.count ?? 0
  return (
    <ol className="space-y-1">
      {funnel.stages.map((stage, i) => {
        const rate = i > 0 ? funnel.rates?.[i - 1] : undefined
        const prev = funnel.stages[i - 1]?.count ?? 0
        return (
          <li key={`${stage.label}-${i}`} className="space-y-1">
            {i > 0 && !compact && (
              <div className="flex items-center gap-1.5 pl-1 text-xs text-muted-foreground">
                <ArrowDown className="size-3" />
                <span className="tabular-nums">{rate ? `${rate.rate}%` : pct(stage.count, prev)} continued</span>
                <span className="text-muted-foreground/60">·</span>
                <span className="tabular-nums">{num(rate?.dropoff_count ?? Math.max(0, prev - stage.count))} dropped off</span>
              </div>
            )}
            <div className="space-y-1">
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="min-w-0 truncate" title={stage.label}>{stage.label}</span>
                <span className="shrink-0 tabular-nums">
                  <span className="font-medium">{num(stage.count)}</span>
                  {i > 0 && <span className="ml-1.5 text-xs text-muted-foreground">{pct(stage.count, first)}</span>}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-[var(--series-1)] transition-[width] duration-500"
                  style={{ width: first ? `${Math.max(stage.count ? 1.5 : 0, (stage.count / first) * 100)}%` : "0%" }} />
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
