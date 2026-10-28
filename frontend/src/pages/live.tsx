import { Fragment, useEffect, useMemo, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Activity, ChevronRight, Eraser, Pause, Play } from "lucide-react"

import { ShortId } from "@/components/client-id"
import { JsonBlock } from "@/components/data-value"
import { DetailSheet, type Detail } from "@/components/detail-sheet"
import { ClearFilters, FilterBar, FilterSelect, FilterSwitch, SearchInput } from "@/components/filters"
import { Page, PageHeader } from "@/components/page-header"
import { EmptyRow, LoadingRows } from "@/components/table-state"
import { SourceText, VisitorBadge } from "@/components/visitor-badge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useUrlFilters } from "@/hooks/use-url-filters"
import { analyticsAPI, apiError } from "@/lib/api"
import { clockTime, fullTime, humanize, num, splitUrl } from "@/lib/format"
import { describe } from "@/lib/nav"
import { cn } from "@/lib/utils"

const POLL_MS = 3000

/** One colour per common event type so the stream scans at a glance. */
const EVENT_COLORS: Record<string, string> = {
  page_view: "var(--series-1)", click: "var(--series-3)", form_submit: "var(--good)", form_input: "var(--series-4)",
  scroll: "var(--series-gray)", navigation: "var(--series-7)", visibility: "var(--series-2)", heartbeat: "var(--series-5)",
}

function EventBadge({ type }: { type: string }) {
  return (
    <Badge variant="outline" className="gap-1.5 font-normal">
      <span className="size-2 rounded-full" style={{ background: EVENT_COLORS[type] ?? "var(--series-gray)" }} />
      {humanize(type)}
    </Badge>
  )
}

const FILTERS = { type: "", site: "", page: "", q: "", humans: "" }

export function LivePage() {
  const [paused, setPaused] = useState(false)
  const [clearedThrough, setClearedThrough] = useState(0)
  const { filters: f, set, clear, active } = useUrlFilters(FILTERS)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)

  // The stream endpoint can't carry the sign-in token, so the page polls (as it always effectively did).
  const { data, isLoading, isError, error, dataUpdatedAt } = useQuery({
    queryKey: ["live-events"], queryFn: () => analyticsAPI.getLiveEvents(100),
    refetchInterval: paused ? false : POLL_MS, refetchIntervalInBackground: false,
  })

  const events = useMemo(() => (data?.events ?? []).filter((e) => e.id > clearedThrough), [data, clearedThrough])
  const types = useMemo(() => [...new Set(events.map((e) => e.event_type))].sort(), [events])
  const sites = useMemo(() => {
    const counts = new Map<string, number>()
    for (const e of events) { const d = e.page_domain || splitUrl(e.page_url).host; if (d) counts.set(d, (counts.get(d) ?? 0) + 1) }
    return [...counts].sort((a, b) => b[1] - a[1]).map(([value, count]) => ({ value, label: value, count }))
  }, [events])
  const page = f.page.toLowerCase()
  const q = f.q.toLowerCase()
  const shown = events.filter((e) =>
    (!f.type || e.event_type === f.type) &&
    (!f.site || (e.page_domain || splitUrl(e.page_url).host) === f.site) &&
    (!page || (e.path || splitUrl(e.page_url).path).toLowerCase().includes(page)) &&
    // An event without a known page view counts as a person's: the tracker only runs in browsers
    (!f.humans || e.is_bot !== true) &&
    (!q || JSON.stringify(e).toLowerCase().includes(q)))
  const bots = events.filter((e) => e.is_bot === true).length

  // Rows that weren't there on the previous poll get a short highlight
  const seen = useRef<Set<number> | null>(null)
  const fresh = useMemo(() => {
    const prev = seen.current
    return new Set(prev ? events.filter((e) => !prev.has(e.id)).map((e) => e.id) : [])
  }, [events])
  useEffect(() => { seen.current = new Set(events.map((e) => e.id)) }, [events])

  return (
    <>
      <PageHeader title="Live events" description={describe("/live-data")}>
        <span className="mr-1 inline-flex items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
          <span className="relative flex size-2" aria-hidden>
            {!paused && <span className="absolute inline-flex size-full animate-ping rounded-full bg-good opacity-50 motion-reduce:animate-none" />}
            <span className={cn("relative inline-flex size-2 rounded-full", paused ? "bg-muted-foreground/60" : "bg-good")} />
          </span>
          {paused ? "Paused" : `Live · every ${POLL_MS / 1000}s`}
          {dataUpdatedAt > 0 && <span className="hidden tabular-nums sm:inline">· {clockTime(new Date(dataUpdatedAt).toISOString())}</span>}
        </span>
        <Button size="sm" variant={paused ? "default" : "outline"} onClick={() => setPaused((p) => !p)}>
          {paused ? <Play /> : <Pause />}{paused ? "Resume" : "Pause"}
        </Button>
        <Button size="sm" variant="outline" disabled={!events.length}
          onClick={() => setClearedThrough(Math.max(clearedThrough, ...events.map((e) => e.id)))}>
          <Eraser />Clear
        </Button>
      </PageHeader>

      <Page>
        <FilterBar>
          <SearchInput label="Search events" placeholder="Search page, visitor, source, data…" value={f.q} onChange={(v) => set({ q: v })} debounce={150} />
          <FilterSelect label="Event type" allLabel="All events" value={f.type} onChange={(type) => set({ type })}
            options={types.map((t) => ({ value: t, label: humanize(t) }))} />
          <FilterSelect label="Site" allLabel="All sites" value={f.site} onChange={(site) => set({ site })} options={sites} />
          <SearchInput label="Page path contains" placeholder="Page contains…" mono className="max-w-48" value={f.page} onChange={(v) => set({ page: v })} debounce={150} />
          <FilterSwitch label={bots ? `Humans only (hides ${num(bots)})` : "Humans only"} checked={!!f.humans} onChange={(v) => set({ humans: v ? "1" : "" })} />
          <ClearFilters active={active} onClear={clear} />
          <span className="ml-auto text-xs text-muted-foreground tabular-nums">
            {shown.length === events.length ? `${num(events.length)} events` : `${num(shown.length)} of ${num(events.length)} events`}
          </span>
        </FilterBar>

        <Card className="overflow-hidden py-0">
          <div className="max-h-[calc(100svh-15rem)] overflow-auto">
            <Table>
              <TableHeader className="sticky top-0 z-10 bg-card">
                <TableRow>
                  <TableHead className="w-8" />
                  <TableHead className="w-24">Time</TableHead>
                  <TableHead>Event</TableHead>
                  <TableHead>Page</TableHead>
                  <TableHead>Visitor</TableHead>
                  <TableHead>Source</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && <LoadingRows cols={6} />}
                {isError && <EmptyRow cols={6} error title="Couldn't load events" description={apiError(error)} />}
                {data && shown.length === 0 && (
                  <EmptyRow cols={6} icon={<Activity />}
                    title={paused ? "Paused" : events.length ? "No events match" : "Waiting for events…"}
                    description={paused ? "Resume to keep receiving events." : events.length ? "Clear a filter to see more of the stream." : "New tracking events appear here within a few seconds."} />
                )}
                {shown.map((e) => {
                  const { host, path } = splitUrl(e.page_url)
                  const open = expanded === e.id
                  const hasData = !!e.event_data && Object.keys(e.event_data).length > 0
                  return (
                    <Fragment key={e.id}>
                      <TableRow data-state={open ? "selected" : undefined}
                        className={cn(hasData && "cursor-pointer", fresh.has(e.id) && "animate-in bg-[color-mix(in_oklch,var(--good),transparent_90%)] duration-700 fade-in-0")}
                        onClick={() => hasData && setExpanded(open ? null : e.id)}>
                        <TableCell className="pr-0">
                          {hasData && <ChevronRight className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-90")} />}
                        </TableCell>
                        <TableCell className="text-muted-foreground tabular-nums" title={fullTime(e.timestamp)}>{clockTime(e.timestamp)}</TableCell>
                        <TableCell><EventBadge type={e.event_type} /></TableCell>
                        <TableCell className="max-w-80">
                          <span className="block truncate" title={e.page_url}>{e.path || path || "—"}<span className="text-muted-foreground">{host && ` · ${host}`}</span></span>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            {e.client_id ? (
                              <button type="button" className="rounded hover:underline" onClick={(ev) => { ev.stopPropagation(); setDetail({ kind: "journey", id: e.client_id! }) }}>
                                <ShortId id={e.client_id} />
                              </button>
                            ) : <span className="text-muted-foreground">—</span>}
                            {e.is_bot && <VisitorBadge label={e.crawler_type || "Bot"} isBot className="h-5 text-[11px]" />}
                          </div>
                        </TableCell>
                        <TableCell className="max-w-48"><SourceText source={e.source} medium={e.medium} campaign={e.campaign} className="block" /></TableCell>
                      </TableRow>
                      {open && (
                        <TableRow className="hover:bg-transparent">
                          <TableCell />
                          <TableCell colSpan={5} className="whitespace-normal"><JsonBlock value={e.event_data} /></TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </Card>
      </Page>

      <DetailSheet detail={detail} onChange={setDetail} />
    </>
  )
}
