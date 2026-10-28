import { lazy, Suspense, useEffect, useRef, useState } from "react"
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowRight, Bot, Download, Eye, FileCheck2, History, MoreHorizontal, Percent, RefreshCw, Trash2, UserRound, Users,
} from "lucide-react"
import { Link, useLocation } from "react-router-dom"
import { toast } from "sonner"

import { BarList } from "@/components/bar-list"
import { ShortId } from "@/components/client-id"
import { DataPagination } from "@/components/data-pagination"
import { DateRangePicker } from "@/components/date-range-picker"
import { DetailSheet, type Detail } from "@/components/detail-sheet"
import {
  ClearFilters, FilterBar, FilterSelect, SearchInput, SuggestInput, VISITOR_OPTIONS, countryName, useFacet,
} from "@/components/filters"
import { FunnelSteps, funnelRate } from "@/components/funnel-steps"
import { Page, PageHeader } from "@/components/page-header"
import { Delta, StatCard } from "@/components/stat-card"
import { EmptyRow, LoadingRows } from "@/components/table-state"
import { KindDot, SourceText, VisitorBadge } from "@/components/visitor-badge"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogMedia, AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useDateRange } from "@/hooks/use-date-range"
import { usePage, useUrlFilters } from "@/hooks/use-url-filters"
import { adminAPI, analyticsAPI, apiError, saveBlob, type Range, type VisitorSummary } from "@/lib/api"
import { fullTime, num, pct, place, plural, previousRange, rangeDays, rangeLabel, relativeTime, splitUrl } from "@/lib/format"
import { describe } from "@/lib/nav"
import { KIND_META, KIND_ORDER, visitorKind, type VisitorKind } from "@/lib/visitors"

// The chart library is the largest dependency; the tiles and tables don't wait for it
const TrendChart = lazy(() => import("@/components/trend-chart").then((m) => ({ default: m.TrendChart })))

const category = (s: VisitorSummary | undefined, name: string) => s?.visits_by_category.find((c) => c.category === name)?.count ?? 0

export function OverviewPage() {
  const [range, setRange] = useDateRange(7)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const queryClient = useQueryClient()

  const summary = useQuery({ queryKey: ["visitor-summary", range], queryFn: () => analyticsAPI.getVisitorSummary(range), refetchInterval: 60_000, placeholderData: keepPreviousData })
  // The same number of days just before, for the change on each tile
  const prevRange = previousRange(range)
  const previous = useQuery({ queryKey: ["visitor-summary", prevRange], queryFn: () => analyticsAPI.getVisitorSummary(prevRange), staleTime: 10 * 60_000 })

  const download = async (kind: "visits" | "events") => {
    const id = toast.loading(`Preparing the ${kind} CSV…`)
    try {
      const res = kind === "visits" ? await analyticsAPI.exportVisitsCSV(range) : await analyticsAPI.exportEventsCSV(range)
      saveBlob(res, `crawldoctor_${kind}_${range.start}_to_${range.end}.csv`)
      toast.success(`Downloaded ${kind}`, { id, description: rangeLabel(range.start, range.end) })
    } catch (e) {
      toast.error("Export failed", { id, description: `${apiError(e)}. For very large datasets, try a shorter range.` })
    }
  }

  const rebuild = useMutation({
    mutationFn: () => adminAPI.rebuildSummaries(30),
    onSuccess: () => toast.success("Rebuilding summaries", { description: "The last 30 days are being reprocessed in the background." }),
    onError: (e) => toast.error("Couldn't start processing", { description: apiError(e) }),
  })

  const wipe = useMutation({
    mutationFn: analyticsAPI.deleteAllVisits,
    onSuccess: () => { queryClient.invalidateQueries(); setConfirmDelete(false); toast.success("All visit data deleted") },
    onError: (e) => toast.error("Delete failed", { description: apiError(e) }),
  })

  const s = summary.data
  const humans = category(s, "Desktop Humans") + category(s, "Mobile Humans")
  const bots = category(s, "AI Crawlers")
  const p = previous.data
  const period = `${plural(rangeDays(range), "day")} (${rangeLabel(prevRange.start, prevRange.end)})`
  const delta = (current: number, before: (v: VisitorSummary) => number, opts: { neutral?: boolean; points?: boolean } = {}) =>
    previous.isError ? undefined : <Delta current={current} previous={p ? before(p) : undefined} period={period} {...opts} />

  return (
    <>
      <PageHeader title="Overview" description={describe("/dashboard")}>
        <DateRangePicker value={range} onChange={setRange} />
        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant="outline" size="icon-sm" aria-label="More actions" />}>
            <MoreHorizontal />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-56">
            <DropdownMenuGroup>
              <DropdownMenuLabel>{rangeLabel(range.start, range.end)}</DropdownMenuLabel>
              <DropdownMenuItem onClick={() => download("visits")}><Download />Export visits as CSV</DropdownMenuItem>
              <DropdownMenuItem onClick={() => download("events")}><Download />Export events as CSV</DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => rebuild.mutate()} disabled={rebuild.isPending}>
              <RefreshCw className={rebuild.isPending ? "animate-spin" : undefined} />Rebuild summaries (30 days)
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={() => setConfirmDelete(true)}><Trash2 />Delete all data…</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </PageHeader>

      <Page>
        {summary.isError && !s ? (
          <Card><CardContent className="text-sm text-destructive">Couldn't load the summary: {apiError(summary.error)}</CardContent></Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
            <StatCard icon={<Eye />} label="Page views" loading={!s} value={num(s?.total_visits)} hint={`Change vs ${rangeLabel(prevRange.start, prevRange.end)}`}
              delta={s && delta(s.total_visits, (v) => v.total_visits, { neutral: true })} />
            <StatCard icon={<Users />} label="Unique visitors" loading={!s} value={num(s?.unique_visitors)}
              delta={s && delta(s.unique_visitors, (v) => v.unique_visitors, { neutral: true })}
              hint={s?.unique_visitors ? `${(s.total_visits / s.unique_visitors).toFixed(1)} views per visitor` : "—"} />
            <StatCard icon={<UserRound />} label="Human visits" loading={!s} value={num(humans)}
              delta={s && delta(humans, (v) => category(v, "Desktop Humans") + category(v, "Mobile Humans"))}
              hint={`${num(category(s, "Desktop Humans"))} desktop · ${num(category(s, "Mobile Humans"))} mobile`} />
            <StatCard icon={<Bot />} label="Bot & crawler visits" loading={!s} value={num(bots)} hint={`${pct(bots, s?.total_visits ?? 0)} of all page views`}
              delta={s && delta(bots, (v) => category(v, "AI Crawlers"), { neutral: true })} />
            <StatCard icon={<FileCheck2 />} label="Conversions" loading={!s} value={num(s?.conversions)} hint="People who submitted a form"
              delta={s && delta(s.conversions, (v) => v.conversions)} />
            <StatCard icon={<Percent />} label="Conversion rate" loading={!s} value={`${s?.conversion_rate ?? 0}%`} hint="Of unique visitors"
              delta={s && delta(s.conversion_rate, (v) => v.conversion_rate, { points: true })} />
          </div>
        )}

        <Suspense fallback={<Skeleton className="h-[338px] rounded-xl" />}><TrendChart range={range} /></Suspense>

        <div className="grid gap-4 lg:grid-cols-5">
          <TrafficMix range={range} className="lg:col-span-3" />
          <TopPages range={range} className="lg:col-span-2" />
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Top sources</CardTitle><CardDescription>Page views by utm_source or referrer</CardDescription></CardHeader>
            <CardContent>
              <BarList loading={!s} total={s?.total_visits}
                rows={(s?.top_sources ?? []).map((r) => ({ key: r.source, label: r.source, value: r.count, color: "var(--series-3)" }))} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Top campaigns</CardTitle><CardDescription>Page views by utm_campaign</CardDescription></CardHeader>
            <CardContent>
              <BarList loading={!s} total={s?.total_visits}
                rows={(s?.top_campaigns ?? []).map((r) => ({
                  key: r.campaign, value: r.count, color: "var(--series-7)",
                  label: r.campaign === "none" ? <span className="text-muted-foreground">No campaign</span> : r.campaign,
                }))} />
            </CardContent>
          </Card>
        </div>

        <FunnelsPreview range={range} />
        <RecentActivity range={range} onOpen={setDetail} />
      </Page>

      <DetailSheet detail={detail} onChange={setDetail} />

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogMedia className="bg-destructive/10 text-destructive"><Trash2 /></AlertDialogMedia>
            <AlertDialogTitle>Delete all visit data?</AlertDialogTitle>
            <AlertDialogDescription>
              Every tracked visit, event and session is removed for good, not just this date range. Export first if you might need it.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" disabled={wipe.isPending} onClick={() => wipe.mutate()}>
              {wipe.isPending ? "Deleting…" : "Delete everything"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

/** Humans vs AI crawlers vs search engines vs other bots, then the crawlers by name. */
function TrafficMix({ range, className }: { range: Range; className?: string }) {
  const { data, isLoading } = useQuery({ queryKey: ["visitor-categories", range], queryFn: () => analyticsAPI.getVisitorCategories(range), refetchInterval: 60_000, placeholderData: keepPreviousData })
  const cats = data?.categories ?? []
  const byKind = Object.fromEntries(KIND_ORDER.map((k) => [k, 0])) as Record<VisitorKind, number>
  for (const c of cats) byKind[visitorKind(c.name, c.name !== "Human")] += c.count
  const total = cats.reduce((a, c) => a + c.count, 0)
  const crawlers = cats
    .filter((c) => visitorKind(c.name, c.name !== "Human") !== "human")
    .sort((a, b) => b.count - a.count)

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Who visited</CardTitle>
        <CardDescription>Page views by visitor type, then each crawler by name</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {isLoading ? <Skeleton className="h-3 rounded-full" /> : (
          <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full bg-muted">
            {KIND_ORDER.filter((k) => byKind[k] > 0).map((k) => (
              <div key={k} className="h-full transition-[width] duration-500 first:rounded-l-full last:rounded-r-full"
                title={`${KIND_META[k].plural}: ${num(byKind[k])}`}
                style={{ width: `${(byKind[k] / Math.max(1, total)) * 100}%`, background: KIND_META[k].color }} />
            ))}
          </div>
        )}
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
          {KIND_ORDER.map((k) => (
            <div key={k} className="space-y-0.5">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground"><KindDot kind={k} />{KIND_META[k].plural}</div>
              <div className="flex items-baseline gap-1.5">
                <span className="text-lg font-semibold tabular-nums">{isLoading ? "–" : num(byKind[k])}</span>
                <span className="text-xs text-muted-foreground tabular-nums">{pct(byKind[k], total)}</span>
              </div>
            </div>
          ))}
        </div>
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">Crawlers and bots</div>
          <BarList loading={isLoading} total={total} empty="No crawler visits in this range."
            rows={crawlers.slice(0, 8).map((c) => {
              const kind = visitorKind(c.name, true)
              return {
                key: c.name, value: c.count, color: KIND_META[kind].color,
                label: <span className="flex items-center gap-2"><KindDot kind={kind} />{c.name}</span>,
                detail: KIND_META[kind].label,
              }
            })} />
        </div>
      </CardContent>
    </Card>
  )
}

/** The most viewed pages by people (not bots), with their site muted. */
function TopPages({ range, className }: { range: Range; className?: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["top-pages", range, "overview"], queryFn: () => analyticsAPI.getTopPages(range, { limit: 10 }),
    refetchInterval: 5 * 60_000, placeholderData: keepPreviousData,
  })
  const views = new Map<string, number>()
  for (const p of data?.pages ?? []) views.set(p.domain, (views.get(p.domain) ?? 0) + p.views)
  const mainSite = [...views].sort((a, b) => b[1] - a[1])[0]?.[0]
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Top pages</CardTitle>
        <CardDescription>Human page views by path, with unique visitors</CardDescription>
        <CardAction>
          <Button variant="ghost" size="sm" nativeButton={false} render={<Link to={`/pages?from=${range.start}&to=${range.end}`} />}>All pages<ArrowRight /></Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <BarList loading={isLoading} showShare={false} empty="No human page views in this range."
          rows={(data?.pages ?? []).map((r) => ({
            key: `${r.domain}${r.path}`, value: r.views, detail: `${num(r.visitors)} unique`,
            // Most views are on the main site; name the site only for the others
            label: <span title={`${r.domain}${r.path}`}><span className="font-mono text-xs">{r.path}</span>
              {r.domain !== mainSite && <span className="text-muted-foreground"> · {r.domain}</span>}</span>,
          }))} />
      </CardContent>
    </Card>
  )
}

function FunnelsPreview({ range }: { range: Range }) {
  const { data, isLoading } = useQuery({ queryKey: ["funnel-summary", range], queryFn: () => analyticsAPI.getFunnelSummary(range), refetchInterval: 60_000, placeholderData: keepPreviousData })
  const funnels = data?.funnels ?? []
  return (
    <Card>
      <CardHeader>
        <CardTitle>Conversion funnels</CardTitle>
        <CardDescription>People who reached each step, in order</CardDescription>
        <CardAction>
          <Button variant="ghost" size="sm" nativeButton={false} render={<Link to={`/funnels?from=${range.start}&to=${range.end}`} />}>Open funnels<ArrowRight /></Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-32" />)}</div>
        ) : funnels.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">No funnels configured yet.</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {funnels.map((f) => (
              <div key={f.key || f.label} className="space-y-3 rounded-lg border p-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="line-clamp-2 text-sm font-medium">{f.label}</span>
                  <span className="shrink-0 text-sm font-semibold tabular-nums">{funnelRate(f).toFixed(1)}%</span>
                </div>
                <FunnelSteps funnel={f} compact />
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

const RECENT_FILTERS = { visitor: "", path: "", source: "", country: "", domain: "" }

function RecentActivity({ range, onOpen }: { range: Range; onOpen: (d: Detail) => void }) {
  const { filters: f, set, clear, active } = useUrlFilters(RECENT_FILTERS)
  const [page, setPage] = usePage(JSON.stringify([range, f]))
  const [size, setSize] = useState(20)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["recent-activity", range, f, page, size],
    queryFn: () => analyticsAPI.getRecentActivity(range, size, (page - 1) * size, f),
    refetchInterval: 30_000, placeholderData: keepPreviousData,
  })

  const crawlers = useQuery({ queryKey: ["visitor-categories", range], queryFn: () => analyticsAPI.getVisitorCategories(range), staleTime: 60_000 })
  const visitorOptions = [
    ...VISITOR_OPTIONS,
    ...(crawlers.data?.categories ?? []).filter((c) => c.name !== "Human").sort((a, b) => b.count - a.count)
      .map((c) => ({ value: c.name, label: c.name, count: c.count })),
  ]
  const countries = useFacet("visits.country", range)
  const domains = useFacet("visits.page_domain", range)
  const sources = useFacet("visits.source", range, true)

  // Links from search and the Pages report (…#recent) land here once the rows are in
  const { hash, key } = useLocation()
  const scrolledFor = useRef<string | null>(null)
  useEffect(() => {
    if (hash !== "#recent" || !data || scrolledFor.current === key) return
    scrolledFor.current = key
    document.getElementById("recent")?.scrollIntoView({ block: "start" })
  }, [hash, key, data])

  return (
    <Card id="recent" className="scroll-mt-20 gap-0 overflow-hidden pb-0">
      <CardHeader className="gap-3 border-b pb-4">
        <CardTitle>Recent page views</CardTitle>
        <CardDescription>Newest first; open a row to see its whole session</CardDescription>
        <FilterBar className="col-span-full mt-1">
          <FilterSelect label="Visitor type" allLabel="All visitors" value={f.visitor} onChange={(visitor) => set({ visitor })} options={visitorOptions} />
          <SearchInput label="Path contains" placeholder="Path contains…" mono className="max-w-56" value={f.path} onChange={(path) => set({ path })} />
          <SuggestInput label="Source contains" placeholder="Source" value={f.source} onChange={(source) => set({ source })}
            suggestions={sources.map((v) => v.value)} />
          <FilterSelect label="Country" allLabel="All countries" value={f.country} onChange={(country) => set({ country })}
            options={countries.map((c) => ({ value: c.value, label: countryName(c.value), count: c.count }))} />
          <FilterSelect label="Site" allLabel="All sites" value={f.domain} onChange={(domain) => set({ domain })}
            options={domains.map((d) => ({ value: d.value, label: d.value, count: d.count }))} />
          <ClearFilters active={active} onClear={clear} />
        </FilterBar>
      </CardHeader>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-28">Time</TableHead>
              <TableHead>Visitor</TableHead>
              <TableHead>Page</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Location</TableHead>
              <TableHead className="w-24">Session</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && <LoadingRows cols={6} />}
            {(isError || data?.error) && <EmptyRow cols={6} error title="Couldn't load recent activity" description={data?.error ?? apiError(error)} />}
            {data && !data.error && data.visits.length === 0 && (
              active ? <EmptyRow cols={6} icon={<History />} title="No page views match" description="Clear a filter or pick a wider date range." />
                : <EmptyRow cols={6} icon={<History />} title="No page views in this range" description="Pick a wider date range, or check that the tracking script is installed." />
            )}
            {data?.visits.map((v) => {
              const { host, path } = splitUrl(v.page_url)
              return (
                <TableRow key={v.id} className="cursor-pointer" onClick={() => v.session_id && onOpen({ kind: "session", id: v.session_id })}>
                  <TableCell className="text-muted-foreground tabular-nums" title={fullTime(v.timestamp)}>{relativeTime(v.timestamp)}</TableCell>
                  <TableCell>
                    <VisitorBadge label={v.crawler_type || (v.is_bot ? "Bot" : "Human")} isBot={v.is_bot} />
                    <div className="mt-1 max-w-56 truncate text-xs text-muted-foreground" title={v.user_agent}>{v.user_agent || "No user agent"}</div>
                  </TableCell>
                  <TableCell className="max-w-80">
                    {v.page_url ? (
                      <a href={v.page_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="block truncate hover:underline" title={v.page_url}>
                        {path}<span className="text-muted-foreground"> · {host}</span>
                      </a>
                    ) : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="max-w-48"><SourceText source={v.source} medium={v.medium} campaign={v.campaign} className="block" /></TableCell>
                  <TableCell className="text-muted-foreground">{place(v.city, v.country) || "—"}</TableCell>
                  <TableCell><ShortId id={v.session_id} /></TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
      <DataPagination data={data} page={page} pageSize={size} onPage={setPage} onPageSize={setSize} approximate />
    </Card>
  )
}
