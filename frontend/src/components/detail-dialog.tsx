import { useEffect, useRef, useState, type ComponentType, type ReactNode, type RefObject } from "react"
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { ArrowLeft, ChevronLeft, ChevronRight, FileCheck2, Loader2, MonitorSmartphone, Route, User, X } from "lucide-react"

import { CopyButton } from "@/components/client-id"
import { DataValue } from "@/components/data-value"
import { ActivityToolbar, FullUrl, NoMatches, Timeline, useActivityFilter } from "@/components/timeline"
import { SessionKind } from "@/components/visitor-badge"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Item, ItemActions, ItemContent, ItemDescription, ItemTitle } from "@/components/ui/item"
import { Kbd } from "@/components/ui/kbd"
import { Skeleton } from "@/components/ui/skeleton"
import { analyticsAPI, type LeadDetail, type TimelineItem } from "@/lib/api"
import { num, place, plural, relativeTime, seconds, shortDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"

/** What the detail view shows: a session, one visitor's journey (with their forms), or a user's activity. */
export type Detail = { kind: "session" | "journey" | "user"; id: string }

/** Lets a view open another (a session's visitor, a user's session) and come back. */
type Nav = { open: (d: Detail) => void; back?: () => void }

const JOURNEY_PAGE = 200

/**
 * Pages keep one `Detail` in state and render this. It opens full screen, so long URLs, form values
 * and event data are shown whole instead of being cut off at the edge of a side panel.
 */
export function DetailDialog({ detail, onChange }: { detail: Detail | null; onChange: (d: Detail | null) => void }) {
  const popup = useRef<HTMLDivElement>(null)
  // Keep the last view on screen while the dialog animates closed
  const [shown, setShown] = useState(detail)
  if (detail && detail !== shown) setShown(detail)
  // Views opened from inside the dialog, so Back returns to where you were
  const [trail, setTrail] = useState<Detail[]>([])
  useEffect(() => { if (!detail) setTrail([]) }, [detail])

  const nav: Nav = {
    open: (next) => { if (detail) setTrail((t) => [...t, detail]); onChange(next) },
    back: trail.length ? () => { onChange(trail[trail.length - 1]); setTrail((t) => t.slice(0, -1)) } : undefined,
  }

  return (
    <DialogPrimitive.Root open={!!detail} onOpenChange={(o) => !o && onChange(null)}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop className="fixed inset-0 z-50 bg-black/40 transition-opacity duration-150 data-ending-style:opacity-0 data-starting-style:opacity-0 supports-backdrop-filter:backdrop-blur-xs" />
        {/* Opened by a click, focus the dialog itself rather than ringing its first button; keyboard keeps the default */}
        <DialogPrimitive.Popup ref={popup} initialFocus={(type) => (type === "keyboard" ? true : popup.current)}
          className="fixed inset-0 z-50 mx-auto flex max-w-[1600px] flex-col overflow-hidden bg-popover text-sm text-popover-foreground shadow-2xl outline-none transition duration-200 ease-out data-ending-style:scale-[0.98] data-ending-style:opacity-0 data-starting-style:scale-[0.98] data-starting-style:opacity-0 sm:inset-3 sm:rounded-xl sm:ring-1 sm:ring-foreground/10 lg:inset-5">
          {shown?.kind === "session" && <SessionView key={shown.id} id={shown.id} nav={nav} />}
          {shown?.kind === "journey" && <JourneyView key={shown.id} id={shown.id} nav={nav} />}
          {shown?.kind === "user" && <UserView key={shown.id} id={shown.id} nav={nav} />}
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

/* ---------- Layout ---------- */

function Header({ icon: Icon, title, id, badges, stats, nav }: {
  icon: ComponentType<{ className?: string }>; title: string; id: string; badges?: ReactNode; stats?: ReactNode; nav: Nav
}) {
  return (
    <header className="flex shrink-0 flex-col gap-4 border-b px-4 py-3 sm:px-6 sm:py-4">
      <div className="flex items-start gap-3">
        {nav.back && (
          <Button variant="ghost" size="icon-sm" className="mt-0.5 -ml-1.5" onClick={nav.back} aria-label="Back"><ArrowLeft /></Button>
        )}
        <span className="hidden size-9 shrink-0 items-center justify-center rounded-lg border bg-muted/50 text-muted-foreground sm:flex">
          <Icon className="size-4" />
        </span>
        <div className="min-w-0 flex-1 space-y-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <DialogPrimitive.Title className="font-heading text-base font-medium">{title}</DialogPrimitive.Title>
            {badges}
          </div>
          <DialogPrimitive.Description render={<div />} className="flex min-w-0 items-center gap-0.5 font-mono text-xs text-muted-foreground">
            <span className="wrap-anywhere">{id}</span>
            <CopyButton value={id} label="Copy ID" className="shrink-0" />
          </DialogPrimitive.Description>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Kbd className="hidden sm:inline-flex">Esc</Kbd>
          <DialogPrimitive.Close render={<Button variant="ghost" size="icon-sm" />}>
            <X /><span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        </div>
      </div>
      {stats && <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:flex sm:flex-wrap sm:gap-x-8">{stats}</dl>}
    </header>
  )
}

function Stat({ label, children, title }: { label: string; children: ReactNode; title?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium tabular-nums wrap-anywhere" title={title}>{children}</dd>
    </div>
  )
}

/**
 * Activity on the left, everything about the person on the right. On wide screens each side
 * scrolls on its own; on phones they stack, the summary first.
 */
function Columns({ aside, toolbar, footer, scrollRef, children }: {
  aside: ReactNode; toolbar?: ReactNode; footer?: ReactNode; scrollRef?: RefObject<HTMLDivElement | null>; children: ReactNode
}) {
  return (
    <div data-detail-body className="min-h-0 flex-1 overflow-y-auto lg:grid lg:grid-cols-[minmax(0,1fr)_25rem] lg:grid-rows-[minmax(0,1fr)] lg:overflow-hidden xl:grid-cols-[minmax(0,1fr)_28rem]">
      <aside className="space-y-7 border-b bg-muted/25 px-4 py-5 sm:px-6 lg:order-last lg:min-h-0 lg:overflow-y-auto lg:border-b-0 lg:border-l lg:px-5">
        {aside}
      </aside>
      <section aria-label="Activity" className="flex min-h-0 flex-col">
        {toolbar && <div className="border-b px-4 py-2.5 sm:px-6">{toolbar}</div>}
        {/* No top padding here: sticky day headings pin to the padding edge, which would let rows show above them */}
        <div ref={scrollRef} className="min-h-0 flex-1 px-4 pb-6 sm:px-6 lg:overflow-y-auto">{children}</div>
        {footer}
      </section>
    </div>
  )
}

function Section({ title, aside, hint, children }: { title: string; aside?: ReactNode; hint?: string; children: ReactNode }) {
  return (
    <section className="space-y-2.5">
      <div>
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h3>
          {aside && <span className="text-xs text-muted-foreground tabular-nums">{aside}</span>}
        </div>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </section>
  )
}

/** Label / value rows whose values wrap in full. */
function Fields({ children }: { children: ReactNode }) {
  return <dl className="divide-y rounded-lg border bg-background px-3">{children}</dl>
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-3 py-2">
      <dt className="text-xs leading-5 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm leading-5 wrap-anywhere">{children ?? <span className="text-muted-foreground">—</span>}</dd>
    </div>
  )
}

const orDash = (v: string | null | undefined) => (v && v !== "none" ? v : null)

function LoadError() {
  return <Alert variant="destructive"><AlertDescription>Couldn't load this. Close it and try again.</AlertDescription></Alert>
}

function AsideSkeleton() {
  return <div className="space-y-3"><Skeleton className="h-4 w-24" /><Skeleton className="h-36" /><Skeleton className="h-4 w-24" /><Skeleton className="h-28" /></div>
}

/** The activity list with its filter, shared by every view. */
function useActivity(items: TimelineItem[] | undefined) {
  const filter = useActivityFilter(items)
  const list = (opts: { loading?: boolean; showVisitor?: boolean; dim?: boolean }) => (
    <div className={cn("pt-1 transition-opacity", opts.dim && "opacity-50")}>
      <Timeline items={filter.shown} loading={opts.loading} showVisitor={opts.showVisitor} expanded={filter.expanded}
        empty={filter.filtered ? <NoMatches onClear={filter.clear} /> : undefined} />
    </div>
  )
  return { filter, toolbar: <ActivityToolbar filter={filter} />, list }
}

/** First touch: where the person came from and the page they landed on. */
function FirstTouch({ step, source, medium, campaign }: {
  step?: TimelineItem; source?: string | null; medium?: string | null; campaign?: string | null
}) {
  const ref = step?.referrer?.trim()
  return (
    <Fields>
      <Field label="Source">{orDash(source ?? step?.source) ?? "direct"}</Field>
      <Field label="Medium">{orDash(medium ?? step?.medium)}</Field>
      <Field label="Campaign">{orDash(campaign ?? step?.campaign)}</Field>
      <Field label="Landing page">{step?.page_url ? <FullUrl url={step.page_url} /> : null}</Field>
      {step && <Field label="Referrer">{ref ? <FullUrl url={ref} /> : <span className="text-muted-foreground">None (direct visit)</span>}</Field>}
      {step?.tracking_id && <Field label="Tracking ID"><span className="font-mono text-xs">{step.tracking_id}</span></Field>}
    </Fields>
  )
}

/** Distinct pages in the order they were first seen, with how often; clicking one filters the activity to it. */
function PagesVisited({ items, onPick }: { items: TimelineItem[]; onPick: (path: string) => void }) {
  const pages = new Map<string, { url: string; path: string; views: number }>()
  for (const i of items) {
    if (i.type !== "visit" || !i.page_url) continue
    let key = i.page_url
    let path = i.page_url
    try { const u = new URL(i.page_url); key = `${u.origin}${u.pathname}`; path = u.pathname } catch { /* keep as is */ }
    const p = pages.get(key)
    if (p) p.views++
    else pages.set(key, { url: key, path, views: 1 })
  }
  if (!pages.size) return <p className="text-sm text-muted-foreground">No page views here.</p>
  return (
    <ol className="divide-y rounded-lg border bg-background">
      {[...pages.values()].map((p, i) => (
        <li key={p.url}>
          <button type="button" onClick={() => onPick(p.path)} title="Show only this page's activity"
            className="flex w-full items-start gap-3 px-3 py-2 text-left hover:bg-muted/60">
            <span className="w-5 shrink-0 text-xs leading-5 text-muted-foreground tabular-nums">{i + 1}</span>
            <FullUrl plain url={p.url} className="min-w-0 flex-1" />
            <span className="shrink-0 text-xs leading-5 text-muted-foreground tabular-nums">{p.views}×</span>
          </button>
        </li>
      ))}
    </ol>
  )
}

/* ---------- Journey (one client ID, with captured forms) ---------- */

async function loadJourney(id: string, page: number): Promise<LeadDetail> {
  const offset = (page - 1) * JOURNEY_PAGE
  // People who never filled a form have no lead record; fall back to their bare timeline.
  try {
    const detail = await analyticsAPI.getLeadDetail(id, JOURNEY_PAGE, offset)
    if (!detail?.error) return detail
  } catch { /* fall through */ }
  return { journey: await analyticsAPI.getJourneyTimeline(id, JOURNEY_PAGE, offset), form_fills: [] }
}

const span = (from?: string | null, to?: string | null) => {
  const a = from ? Date.parse(from) : Number.NaN
  const b = to ? Date.parse(to) : Number.NaN
  return Number.isNaN(a) || Number.isNaN(b) ? "—" : seconds(Math.max(0, (b - a) / 1000))
}

function JourneyView({ id, nav }: { id: string; nav: Nav }) {
  const [page, setPage] = useState(1)
  const scroller = useRef<HTMLDivElement>(null)
  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["journey-detail", id, page], queryFn: () => loadJourney(id, page), placeholderData: keepPreviousData,
  })
  // The first page has the first touch, whichever page is open
  const firstPage = useQuery({ queryKey: ["journey-detail", id, 1], queryFn: () => loadJourney(id, 1) })
  const total = data?.journey?.total_count ?? data?.journey?.timeline.length ?? 0
  // On a long journey the latest step is on the last page; fetch just that one step for "Last seen"
  const lastStep = useQuery({
    queryKey: ["journey-last", id, total], queryFn: () => analyticsAPI.getJourneyTimeline(id, 1, total - 1), enabled: total > JOURNEY_PAGE,
  })

  const timeline = data?.journey?.timeline
  const { filter, toolbar, list } = useActivity(timeline)
  const fills = data?.form_fills ?? []
  const latest = data?.latest_capture?.form_values
  const params = data?.url_params && Object.keys(data.url_params).length ? data.url_params : null
  const paged = !!(data?.journey?.has_prev || data?.journey?.has_next)
  const first = firstPage.data?.journey?.timeline
  const landing = first?.find((t) => t.type === "visit") ?? first?.[0]
  const firstSeen = first?.[0]?.timestamp
  const lastSeen = total > JOURNEY_PAGE ? lastStep.data?.timeline?.[0]?.timestamp : timeline?.at(-1)?.timestamp

  const goTo = (p: number) => {
    setPage(p)
    scroller.current?.scrollTo({ top: 0 })
    scroller.current?.closest("[data-detail-body]")?.scrollTo({ top: 0 })
  }

  return (
    <>
      <Header icon={Route} title="Visitor journey" id={id} nav={nav}
        badges={fills.length > 0 && <Badge variant="outline" className="gap-1 font-normal text-good"><FileCheck2 />{plural(fills.length, "form submission")}</Badge>}
        stats={data && (
          <>
            <Stat label="Steps tracked">{num(total)}</Stat>
            <Stat label="First seen" title={firstSeen ?? undefined}>{shortDateTime(firstSeen)}</Stat>
            <Stat label="Last seen" title={lastSeen ?? undefined}>{shortDateTime(lastSeen)}</Stat>
            <Stat label="Time span">{span(firstSeen, lastSeen)}</Stat>
            <Stat label="Form submissions">{num(fills.length)}</Stat>
          </>
        )} />
      {isError ? <div className="p-6"><LoadError /></div> : (
        <Columns scrollRef={scroller} toolbar={toolbar}
          aside={isLoading ? <AsideSkeleton /> : (
            <>
              {fills.length > 0 ? (
                <Section title="Form submissions" aside="oldest first">
                  <div className="space-y-3">
                    {fills.map((f, i) => (
                      <div key={f.id ?? i} className="overflow-hidden rounded-lg border bg-background">
                        <div className="flex items-center justify-between gap-2 border-b bg-[color-mix(in_oklch,var(--good),transparent_94%)] px-3 py-2 text-xs">
                          <span className="flex items-center gap-1.5 font-medium text-good"><FileCheck2 className="size-3.5" />Submission {i + 1}</span>
                          <time className="text-muted-foreground tabular-nums" title={f.timestamp}>{shortDateTime(f.timestamp)}</time>
                        </div>
                        <div className="space-y-2 px-3 pt-2 pb-1">
                          {f.page_url ? <FullUrl url={f.page_url} /> : f.path && <span className="font-mono text-xs">{f.path}</span>}
                          <DataValue value={f.form_values} />
                        </div>
                      </div>
                    ))}
                  </div>
                </Section>
              ) : latest ? (
                <Section title="Captured values"><div className="rounded-lg border bg-background px-3 py-1"><DataValue value={latest} /></div></Section>
              ) : null}

              <Section title="First touch">
                {firstPage.isLoading ? <Skeleton className="h-36" /> : <FirstTouch step={landing} />}
              </Section>

              {params && (
                <Section title="Form page parameters" hint="Query parameters on the page of the latest form submission">
                  <div className="rounded-lg border bg-background px-3 py-1"><DataValue value={params} /></div>
                </Section>
              )}

              <Section title="Pages visited" aside={paged ? "on this page of steps" : undefined}>
                <PagesVisited items={timeline ?? []} onPick={(path) => { filter.setKind("all"); filter.setQuery(path) }} />
              </Section>
            </>
          )}
          footer={paged && (
            <div className="flex items-center justify-between gap-3 border-t px-4 py-2.5 text-xs text-muted-foreground sm:px-6">
              <span className="flex items-center gap-2 tabular-nums">
                Steps {num((page - 1) * JOURNEY_PAGE + 1)}–{num((page - 1) * JOURNEY_PAGE + (timeline?.length ?? 0))} of {num(total)}
                {isFetching && <Loader2 className="size-3.5 animate-spin" />}
              </span>
              <div className="flex gap-1">
                <Button variant="outline" size="sm" disabled={!data?.journey?.has_prev || isFetching} onClick={() => goTo(Math.max(1, page - 1))}><ChevronLeft />Earlier</Button>
                <Button variant="outline" size="sm" disabled={!data?.journey?.has_next || isFetching} onClick={() => goTo(page + 1)}>Later<ChevronRight /></Button>
              </div>
            </div>
          )}>
          {list({ loading: isLoading, dim: isFetching && !isLoading })}
        </Columns>
      )}
    </>
  )
}

/* ---------- Session ---------- */

function SessionView({ id, nav }: { id: string; nav: Nav }) {
  const { data, isLoading, isError } = useQuery({ queryKey: ["session-detail", id], queryFn: () => analyticsAPI.getSessionDetail(id) })
  const s = data?.session
  const { toolbar, list } = useActivity(data?.timeline)
  const visits = data?.timeline.filter((t) => t.type === "visit") ?? []
  const events = (data?.timeline.length ?? 0) - visits.length
  const entry = visits[0]

  return (
    <>
      <Header icon={MonitorSmartphone} title="Session" id={id} nav={nav}
        badges={s?.classification && <SessionKind classification={s.classification} />}
        stats={data && (
          <>
            <Stat label="Page views">{num(visits.length)}</Stat>
            <Stat label="Events">{num(events)}</Stat>
            <Stat label="Location">{place(s?.city, s?.country) || "—"}</Stat>
            <Stat label="Started" title={s?.first_visit ?? undefined}>{shortDateTime(s?.first_visit)}</Stat>
            <Stat label="Duration">{span(s?.first_visit, s?.last_visit)}</Stat>
          </>
        )} />
      {isError ? <div className="p-6"><LoadError /></div> : (
        <Columns toolbar={toolbar}
          aside={isLoading ? <AsideSkeleton /> : (
            <>
              {s?.client_id && (
                <Section title="Visitor">
                  <div className="space-y-3 rounded-lg border bg-background p-3">
                    <div className="flex items-start gap-0.5 font-mono text-xs">
                      <span className="min-w-0 pt-0.5 wrap-anywhere">{s.client_id}</span>
                      <CopyButton value={s.client_id} label="Copy visitor ID" className="shrink-0 text-muted-foreground" />
                    </div>
                    <Button variant="outline" size="sm" className="w-full" onClick={() => nav.open({ kind: "journey", id: s.client_id! })}>
                      <Route />Open this visitor's whole journey
                    </Button>
                  </div>
                </Section>
              )}
              <Section title="Entry">
                <FirstTouch step={entry} />
              </Section>
              <Section title="Device and locale">
                <Fields>
                  <Field label="Language">{orDash(s?.client_side_language)}</Field>
                  <Field label="Time zone">{orDash(s?.client_side_timezone)}</Field>
                  <Field label="Screen">{orDash(s?.client_side_screen_resolution)}</Field>
                  <Field label="Viewport">{orDash(s?.client_side_viewport_size)}</Field>
                  <Field label="Device memory">{orDash(s?.client_side_device_memory)}</Field>
                  <Field label="Connection">{orDash(s?.client_side_connection_type)}</Field>
                </Fields>
              </Section>
            </>
          )}>
          {list({ loading: isLoading })}
        </Columns>
      )}
    </>
  )
}

/* ---------- Unified user ---------- */

function UserView({ id, nav }: { id: string; nav: Nav }) {
  const { data, isLoading, isError } = useQuery({ queryKey: ["user-activity", id], queryFn: () => analyticsAPI.getUnifiedUserActivity(id) })
  const a = data?.attribution
  const sum = data?.summary
  const conversions = sum?.conversions ?? 0
  const { toolbar, list } = useActivity(data?.timeline)
  const landing = data?.timeline?.find((t) => t.type === "visit")

  return (
    <>
      <Header icon={User} title="User" id={id} nav={nav}
        badges={conversions > 0 && <Badge variant="outline" className="gap-1 font-normal text-good"><FileCheck2 />{plural(conversions, "conversion")}</Badge>}
        stats={data && (
          <>
            <Stat label="Sessions">{num(sum?.unique_sessions)}</Stat>
            <Stat label="Page views">{num(sum?.total_visits)}</Stat>
            <Stat label="Events">{num(sum?.total_events)}</Stat>
            <Stat label="Domains">{num(sum?.unique_domains)}</Stat>
            <Stat label="Conversions">{num(conversions)}</Stat>
            <Stat label="First seen" title={sum?.first_seen ?? undefined}>{shortDateTime(sum?.first_seen)}</Stat>
            <Stat label="Last seen" title={sum?.last_seen ?? undefined}>{shortDateTime(sum?.last_seen)}</Stat>
          </>
        )} />
      {isError ? <div className="p-6"><LoadError /></div> : (
        <Columns toolbar={toolbar}
          aside={isLoading ? <AsideSkeleton /> : (
            <>
              <Section title="First-touch attribution">
                <FirstTouch step={landing ?? (a?.landing_page ? { type: "visit", id: "landing", page_url: a.landing_page } : undefined)}
                  source={a?.source} medium={a?.medium} campaign={a?.campaign} />
              </Section>
              {!!data?.sessions?.length && (
                <Section title="Sessions" aside={num(data.sessions.length)}>
                  <div className="space-y-1.5">
                    {data.sessions.map((s) => (
                      <Item key={s.session_id} variant="outline" size="sm" render={<button type="button" />}
                        className="w-full bg-background text-left" onClick={() => nav.open({ kind: "session", id: s.session_id })}>
                        <ItemContent className="min-w-0">
                          <ItemTitle className="font-mono text-xs wrap-anywhere">{s.session_id}</ItemTitle>
                          <ItemDescription>{place(s.city, s.country) || "Location unknown"} · {plural(s.visit_count, "visit")}</ItemDescription>
                        </ItemContent>
                        <ItemActions className="text-xs text-muted-foreground tabular-nums">
                          {relativeTime(s.last_visit)}<ChevronRight className="size-4" />
                        </ItemActions>
                      </Item>
                    ))}
                  </div>
                </Section>
              )}
            </>
          )}>
          {list({ loading: isLoading })}
        </Columns>
      )}
    </>
  )
}
