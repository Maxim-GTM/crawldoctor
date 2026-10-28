import { useMemo } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { Skeleton } from "@/components/ui/skeleton"
import { analyticsAPI, type Range } from "@/lib/api"
import { dayLabel, eachDay, num } from "@/lib/format"
import { KIND_META, KIND_ORDER, visitorKind, type VisitorKind } from "@/lib/visitors"

const config = Object.fromEntries(KIND_ORDER.map((k) => [k, { label: KIND_META[k].plural, color: KIND_META[k].color }])) satisfies ChartConfig

/** Page views per day, humans vs each kind of bot, stacked. */
export function TrendChart({ range, className }: { range: Range; className?: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["timeseries", range], queryFn: () => analyticsAPI.getTimeSeries(range),
    refetchInterval: 5 * 60_000, placeholderData: keepPreviousData,
  })

  const rows = useMemo(() => {
    const byDay = new Map(eachDay(range).map((d) => [d, { day: d, human: 0, ai: 0, search: 0, bot: 0 } as Record<VisitorKind, number> & { day: string }]))
    for (const r of data?.series ?? []) {
      const row = byDay.get(r.day)
      if (row) row[visitorKind(r.name, r.name !== "Human")] += r.count
    }
    return [...byDay.values()]
  }, [data, range])
  const single = rows.length <= 1

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Daily page views</CardTitle>
        <CardDescription>Humans and each kind of bot, per UTC day</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? <Skeleton className="h-[240px]" /> : isError ? (
          <p className="py-16 text-center text-sm text-destructive">Couldn't load the daily trend.</p>
        ) : (
          <ChartContainer config={config} className="h-[240px] w-full">
            <BarChart data={rows} margin={{ left: 0, right: 4, top: 4 }} barCategoryGap={single ? "60%" : "12%"}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="day" tickLine={false} axisLine={false} tickMargin={8} minTickGap={24} tickFormatter={dayLabel} />
              <YAxis tickLine={false} axisLine={false} width={44} tickFormatter={(v: number) => (v >= 1000 ? `${Math.round(v / 100) / 10}k` : String(v))} />
              <ChartTooltip cursor={{ fill: "var(--muted)", opacity: 0.5 }}
                content={<ChartTooltipContent labelFormatter={(d) => dayLabel(String(d))} formatter={(v, name) => (
                  <div className="flex w-full items-center justify-between gap-3">
                    <span className="flex items-center gap-1.5 text-muted-foreground">
                      <span className="size-2 rounded-[2px]" style={{ background: KIND_META[name as VisitorKind].color }} />
                      {KIND_META[name as VisitorKind].plural}
                    </span>
                    <span className="font-mono font-medium tabular-nums">{num(Number(v))}</span>
                  </div>
                )} />} />
              <ChartLegend content={<ChartLegendContent />} />
              {KIND_ORDER.map((k, i) => (
                <Bar key={k} dataKey={k} stackId="views" fill={`var(--color-${k})`}
                  radius={i === KIND_ORDER.length - 1 ? [3, 3, 0, 0] : 0} />
              ))}
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}
