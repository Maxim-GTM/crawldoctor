import { useEffect, useRef, useState, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, ExternalLink, FileCheck2, MapPin, Route } from "lucide-react"

import { CopyButton } from "@/components/client-id"
import { DataValue } from "@/components/data-value"
import { Timeline } from "@/components/timeline"
import { SessionKind, SourceText } from "@/components/visitor-badge"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Item, ItemActions, ItemContent, ItemDescription, ItemTitle } from "@/components/ui/item"
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { analyticsAPI, type LeadDetail } from "@/lib/api"
import { fullTime, num, place, plural, relativeTime, splitUrl } from "@/lib/format"

/** What a detail panel shows: a session, one visitor's journey (with their forms), or a user's activity. */
export type Detail = { kind: "session" | "journey" | "user"; id: string }

const JOURNEY_PAGE = 200

/** Pages keep one `Detail` in state and render this; panels can hand over to each other. */
export function DetailSheet({ detail, onChange }: { detail: Detail | null; onChange: (d: Detail | null) => void }) {
  const popup = useRef<HTMLDivElement>(null)
  return (
    <Sheet open={!!detail} onOpenChange={(o) => !o && onChange(null)}>
      {/* Opened by a click, focus the panel itself rather than ringing its first button; keyboard keeps the default */}
      <SheetContent ref={popup} initialFocus={(type) => (type === "keyboard" ? true : popup.current)}
        className="flex w-full flex-col gap-0 overflow-hidden sm:max-w-2xl">
        {detail?.kind === "session" && <SessionPanel id={detail.id} onOpen={onChange} />}
        {detail?.kind === "journey" && <JourneyPanel key={detail.id} id={detail.id} />}
        {detail?.kind === "user" && <UserPanel id={detail.id} onOpen={onChange} />}
      </SheetContent>
    </Sheet>
  )
}

function Header({ title, id, children }: { title: string; id: string; children?: ReactNode }) {
  return (
    <SheetHeader className="gap-2 border-b pb-3">
      <SheetTitle className="pr-8">{title}</SheetTitle>
      <SheetDescription render={<div />} className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="flex items-center gap-0.5 font-mono text-xs">
          {id}<CopyButton value={id} label="Copy ID" className="text-muted-foreground" />
        </span>
        {children}
      </SheetDescription>
    </SheetHeader>
  )
}

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  )
}

const Body = ({ children }: { children: ReactNode }) => (
  <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-4">{children}</div>
)

function LoadError() {
  return <Alert variant="destructive"><AlertDescription>Couldn't load this. Close the panel and try again.</AlertDescription></Alert>
}

/* ---------- Session ---------- */

function SessionPanel({ id, onOpen }: { id: string; onOpen: (d: Detail) => void }) {
  const { data, isLoading, isError } = useQuery({ queryKey: ["session-detail", id], queryFn: () => analyticsAPI.getSessionDetail(id) })
  const s = data?.session
  const loc = place(s?.city, s?.country)
  const visits = data?.timeline.filter((t) => t.type === "visit").length ?? 0
  const events = (data?.timeline.length ?? 0) - visits

  return (
    <>
      <Header title="Session" id={id}>
        {s?.classification && <SessionKind classification={s.classification} />}
        {loc && <span className="flex items-center gap-1 text-xs"><MapPin className="size-3" />{loc}</span>}
        {data && <span className="text-xs tabular-nums">{plural(visits, "page view")} · {plural(events, "event")}</span>}
      </Header>
      <Body>
        {isError ? <LoadError /> : (
          <Section title="Timeline">
            <Timeline items={data?.timeline} loading={isLoading} />
          </Section>
        )}
      </Body>
      {s?.client_id && (
        <SheetFooter className="border-t">
          <Button variant="outline" onClick={() => onOpen({ kind: "journey", id: s.client_id! })}>
            <Route />Open this visitor's journey
          </Button>
        </SheetFooter>
      )}
    </>
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

function JourneyPanel({ id }: { id: string }) {
  const [page, setPage] = useState(1)
  useEffect(() => setPage(1), [id])
  const { data, isLoading, isError, isFetching } = useQuery({ queryKey: ["journey-detail", id, page], queryFn: () => loadJourney(id, page) })

  const fills = data?.form_fills ?? []
  const latest = data?.latest_capture?.form_values
  const params = data?.url_params && Object.keys(data.url_params).length ? data.url_params : null
  const paged = data?.journey?.has_prev || data?.journey?.has_next

  return (
    <>
      <Header title="Visitor journey" id={id}>
        {fills.length > 0 && (
          <Badge variant="outline" className="gap-1 font-normal text-good"><FileCheck2 />{plural(fills.length, "form submission")}</Badge>
        )}
      </Header>
      <Body>
        {isError ? <LoadError /> : isLoading ? (
          <div className="space-y-3"><Skeleton className="h-24" /><Skeleton className="h-40" /></div>
        ) : (
          <>
            {fills.length > 0 ? (
              <Section title="Form submissions" aside={<span className="text-xs text-muted-foreground">oldest first</span>}>
                <div className="space-y-3">
                  {fills.map((f, i) => (
                    <div key={f.id ?? i} className="rounded-lg border p-3">
                      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-xs text-muted-foreground">
                        <span className="tabular-nums">{fullTime(f.timestamp)}</span>
                        {f.page_url ? (
                          <a href={f.page_url} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-full items-center gap-1 truncate text-link hover:underline">
                            {f.path || splitUrl(f.page_url).path}<ExternalLink className="size-3 shrink-0" />
                          </a>
                        ) : f.path}
                      </div>
                      <DataValue value={f.form_values} />
                    </div>
                  ))}
                </div>
              </Section>
            ) : latest ? (
              <Section title="Captured values"><div className="rounded-lg border p-3"><DataValue value={latest} /></div></Section>
            ) : null}

            {params && (
              <Section title="First-touch URL parameters"><div className="rounded-lg border p-3"><DataValue value={params} /></div></Section>
            )}

            <Section title="Activity" aside={isFetching ? <span className="text-xs text-muted-foreground">Loading…</span> : null}>
              <Timeline items={data?.journey?.timeline} />
            </Section>
          </>
        )}
      </Body>
      {paged && (
        <SheetFooter className="flex-row items-center justify-between border-t text-xs text-muted-foreground">
          <span className="tabular-nums">Events {num((page - 1) * JOURNEY_PAGE + 1)}–{num((page - 1) * JOURNEY_PAGE + (data?.journey?.timeline.length ?? 0))}</span>
          <div className="flex gap-1">
            <Button variant="outline" size="sm" disabled={!data?.journey?.has_prev} onClick={() => setPage((p) => Math.max(1, p - 1))}><ChevronLeft />Earlier</Button>
            <Button variant="outline" size="sm" disabled={!data?.journey?.has_next} onClick={() => setPage((p) => p + 1)}>Later<ChevronRight /></Button>
          </div>
        </SheetFooter>
      )}
    </>
  )
}

/* ---------- Unified user ---------- */

function Stat({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="rounded-lg border px-3 py-2">
      <div className="truncate text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{num(value)}</div>
    </div>
  )
}

function UserPanel({ id, onOpen }: { id: string; onOpen: (d: Detail) => void }) {
  const { data, isLoading, isError } = useQuery({ queryKey: ["user-activity", id], queryFn: () => analyticsAPI.getUnifiedUserActivity(id) })
  const a = data?.attribution
  const conversions = data?.summary?.conversions ?? 0

  return (
    <>
      <Header title="User" id={id}>
        {conversions > 0 && <Badge variant="outline" className="gap-1 font-normal text-good"><FileCheck2 />{plural(conversions, "conversion")}</Badge>}
      </Header>
      <Body>
        {isError ? <LoadError /> : isLoading ? (
          <div className="space-y-3"><Skeleton className="h-24" /><Skeleton className="h-16" /><Skeleton className="h-40" /></div>
        ) : (
          <>
            <Section title="First-touch attribution">
              <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-lg border p-3 text-sm sm:grid-cols-4">
                <div><dt className="text-xs text-muted-foreground">Source</dt><dd className="truncate font-medium">{a?.source || "direct"}</dd></div>
                <div><dt className="text-xs text-muted-foreground">Medium</dt><dd className="truncate font-medium">{a?.medium || "none"}</dd></div>
                <div className="col-span-2"><dt className="text-xs text-muted-foreground">Campaign</dt><dd className="truncate font-medium" title={a?.campaign}>{a?.campaign || "—"}</dd></div>
                <div className="col-span-full"><dt className="text-xs text-muted-foreground">Landing page</dt>
                  <dd className="truncate font-mono text-xs" title={a?.landing_page}>{a?.landing_page?.split("?")[0] || "—"}</dd></div>
              </dl>
            </Section>

            <div className="@container"><div className="grid grid-cols-3 gap-2 @lg:grid-cols-5">
              <Stat label="Sessions" value={data?.summary?.unique_sessions} />
              <Stat label="Page views" value={data?.summary?.total_visits} />
              <Stat label="Events" value={data?.summary?.total_events} />
              <Stat label="Domains" value={data?.summary?.unique_domains} />
              <Stat label="Conversions" value={conversions} />
            </div></div>

            {!!data?.sessions?.length && (
              <Section title={`Sessions · ${num(data.sessions.length)}`}>
                <div className="max-h-64 space-y-1.5 overflow-y-auto">
                  {data.sessions.map((s) => (
                    <Item key={s.session_id} variant="outline" size="sm" render={<button type="button" />}
                      className="w-full text-left" onClick={() => onOpen({ kind: "session", id: s.session_id })}>
                      <ItemContent>
                        <ItemTitle className="font-mono text-xs">{s.session_id.slice(0, 16)}…</ItemTitle>
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

            <Section title="Complete timeline" aside={a?.source ? <SourceText source={a.source} medium={a.medium} className="text-xs" /> : null}>
              <Timeline items={data?.timeline} />
            </Section>
          </>
        )}
      </Body>
    </>
  )
}
