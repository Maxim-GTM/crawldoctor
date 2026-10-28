import { useMemo, useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"
import { ChevronRight, Eye, FileCheck2, Inbox, Sparkles, UserRound } from "lucide-react"

import { BarList } from "@/components/bar-list"
import { ShortId } from "@/components/client-id"
import { DateRangePicker } from "@/components/date-range-picker"
import { DetailSheet, type Detail } from "@/components/detail-sheet"
import { Page, PageHeader } from "@/components/page-header"
import { StatCard } from "@/components/stat-card"
import { EmptyRow, LoadingRows } from "@/components/table-state"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useDateRange } from "@/hooks/use-date-range"
import { analyticsAPI, apiError } from "@/lib/api"
import { dayLabel, eachDay, fullTime, num, pct, relativeTime } from "@/lib/format"
import { describe } from "@/lib/nav"

const ASSISTANT_COLORS: Record<string, string> = {
  ChatGPT: "var(--series-3)", Gemini: "var(--series-1)", Claude: "var(--series-2)", Perplexity: "var(--series-7)",
  Copilot: "var(--series-5)", DeepSeek: "var(--series-4)",
}
const colorOf = (a: string) => ASSISTANT_COLORS[a] ?? "var(--series-gray)"
const key = (a: string) => a.toLowerCase().replace(/[^a-z0-9]+/g, "-")

export function AiReferralsPage() {
  const [range, setRange] = useDateRange(30)
  const [detail, setDetail] = useState<Detail | null>(null)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["ai-referrals", range], queryFn: () => analyticsAPI.getAiReferrals(range), placeholderData: keepPreviousData,
  })
  const assistants = data?.assistants ?? []

  const { rows, config } = useMemo(() => {
    const names = assistants.map((a) => a.assistant)
    const byDay = new Map(eachDay(range).map((d) => [d, Object.fromEntries([["day", d], ...names.map((n) => [key(n), 0])])]))
    for (const r of data?.daily ?? []) {
      const row = byDay.get(r.day)
      if (row) row[key(r.assistant)] = ((row[key(r.assistant)] as number) ?? 0) + r.views
    }
    return {
      rows: [...byDay.values()],
      config: Object.fromEntries(names.map((n) => [key(n), { label: n, color: colorOf(n) }])) satisfies ChartConfig,
    }
  }, [data, range, assistants])

  return (
    <>
      <PageHeader title="AI referrals" description={describe("/ai-referrals")}>
        <DateRangePicker value={range} onChange={setRange} />
      </PageHeader>
      <Page>
        {isError && <Card><CardContent className="text-sm text-destructive">Couldn't load AI referrals: {apiError(error)}</CardContent></Card>}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard icon={<Eye />} label="Page views" loading={!data} value={num(data?.views)} hint="By people arriving from an assistant" />
          <StatCard icon={<UserRound />} label="People" loading={!data} value={num(data?.visitors)}
            hint={data?.visitors ? `${(data.views / data.visitors).toFixed(1)} views each` : "—"} />
          <StatCard icon={<FileCheck2 />} label="Leads" loading={!data} value={num(data?.leads.length)} hint="First touch from an assistant" />
          <StatCard icon={<Sparkles />} label="Top assistant" loading={!data} value={assistants[0]?.assistant ?? "—"}
            hint={assistants[0] ? `${pct(assistants[0].views, data?.views ?? 0)} of these views` : "No AI referrals in this range"} />
        </div>

        <div className="grid gap-4 lg:grid-cols-5">
          <Card className="lg:col-span-2">
            <CardHeader><CardTitle>By assistant</CardTitle><CardDescription>Page views, with the people behind them</CardDescription></CardHeader>
            <CardContent>
              <BarList loading={isLoading} total={data?.views} empty="No AI referrals in this range."
                rows={assistants.map((a) => ({
                  key: a.assistant, value: a.views, color: colorOf(a.assistant), detail: `${num(a.visitors)} people`,
                  label: <span className="flex items-center gap-2"><span className="size-2 rounded-full" style={{ background: colorOf(a.assistant) }} />{a.assistant}</span>,
                }))} />
            </CardContent>
          </Card>
          <Card className="lg:col-span-3">
            <CardHeader><CardTitle>Per day</CardTitle><CardDescription>Page views from each assistant, per UTC day</CardDescription></CardHeader>
            <CardContent>
              {isLoading ? <Skeleton className="h-[220px]" /> : (
                <ChartContainer config={config} className="h-[220px] w-full">
                  <BarChart data={rows} margin={{ left: 0, right: 4, top: 4 }}>
                    <CartesianGrid vertical={false} />
                    <XAxis dataKey="day" tickLine={false} axisLine={false} tickMargin={8} minTickGap={24} tickFormatter={dayLabel} />
                    <YAxis tickLine={false} axisLine={false} width={32} allowDecimals={false} />
                    <ChartTooltip cursor={{ fill: "var(--muted)", opacity: 0.5 }} content={<ChartTooltipContent labelFormatter={(d) => dayLabel(String(d))} />} />
                    <ChartLegend content={<ChartLegendContent />} />
                    {assistants.map((a) => <Bar key={a.assistant} dataKey={key(a.assistant)} stackId="ai" fill={`var(--color-${key(a.assistant)})`} />)}
                  </BarChart>
                </ChartContainer>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <Card className="gap-0 overflow-hidden pb-0">
            <CardHeader className="border-b pb-4"><CardTitle>Landing pages</CardTitle><CardDescription>Where assistants send people</CardDescription></CardHeader>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow><TableHead>Page</TableHead><TableHead className="text-right">Views</TableHead><TableHead className="text-right">People</TableHead></TableRow>
                </TableHeader>
                <TableBody>
                  {isLoading && <LoadingRows cols={3} rows={5} />}
                  {data && !data.pages.length && <EmptyRow cols={3} icon={<Sparkles />} title="No AI referrals in this range" />}
                  {data?.pages.map((p) => (
                    <TableRow key={`${p.domain}${p.path}`}>
                      <TableCell className="max-w-96">
                        <a href={`https://${p.domain}${p.path}`} target="_blank" rel="noopener noreferrer" className="block truncate font-mono text-xs hover:underline">{p.path}</a>
                        <div className="truncate text-xs text-muted-foreground">{p.domain}</div>
                      </TableCell>
                      <TableCell className="text-right font-medium tabular-nums">{num(p.views)}</TableCell>
                      <TableCell className="text-right tabular-nums">{num(p.visitors)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>

          <Card className="gap-0 overflow-hidden pb-0">
            <CardHeader className="border-b pb-4"><CardTitle>Leads</CardTitle><CardDescription>People whose first touch was an assistant; open one for their journey</CardDescription></CardHeader>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow><TableHead>Lead</TableHead><TableHead>Assistant</TableHead><TableHead>Captured on</TableHead><TableHead>When</TableHead><TableHead className="w-8" /></TableRow>
                </TableHeader>
                <TableBody>
                  {isLoading && <LoadingRows cols={5} rows={5} />}
                  {data && !data.leads.length && <EmptyRow cols={5} icon={<Inbox />} title="No leads from assistants in this range" />}
                  {data?.leads.map((l) => (
                    <TableRow key={l.client_id} className="cursor-pointer" onClick={() => setDetail({ kind: "journey", id: l.client_id })}>
                      <TableCell className="max-w-56">
                        {l.name || l.email ? (
                          <>
                            <div className="truncate font-medium">{l.name || l.email}</div>
                            {l.name && l.email && <div className="truncate text-xs text-muted-foreground">{l.email}</div>}
                          </>
                        ) : <ShortId id={l.client_id} />}
                      </TableCell>
                      <TableCell>
                        {l.assistant && <Badge variant="outline" className="gap-1.5 font-normal"><span className="size-2 rounded-full" style={{ background: colorOf(l.assistant) }} />{l.assistant}</Badge>}
                      </TableCell>
                      <TableCell className="font-mono text-xs">{l.captured_path || "—"}</TableCell>
                      <TableCell className="tabular-nums" title={fullTime(l.captured_at)}>{relativeTime(l.captured_at)}</TableCell>
                      <TableCell><ChevronRight className="size-4 text-muted-foreground" /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        </div>
        <p className="text-xs text-muted-foreground">
          Counts human page views whose source (utm_source or referrer) is an assistant, e.g. chatgpt.com or gemini.google.com.
          Later pages in the same visit carry an internal source, so they aren't included.
        </p>
      </Page>
      <DetailSheet detail={detail} onChange={setDetail} />
    </>
  )
}
