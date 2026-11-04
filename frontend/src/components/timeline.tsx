import { useMemo, useState, type ReactNode } from "react"
import { ChevronRight, Eye, FileCheck2, Fingerprint, MapPin, MousePointerClick, Navigation, Tag, Zap } from "lucide-react"

import { CopyButton } from "@/components/client-id"
import { DataValue, JsonBlock } from "@/components/data-value"
import { SearchInput } from "@/components/filters"
import { SourceText, VisitorBadge } from "@/components/visitor-badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import type { TimelineItem } from "@/lib/api"
import { clockTime, fullTime, humanize, num, place, seconds } from "@/lib/format"
import { cn } from "@/lib/utils"

const ICONS: Record<string, typeof Eye> = {
  visit: Eye, page_view: Eye, click: MousePointerClick, form_submit: FileCheck2, navigation: Navigation,
}

/** Silence this long between two steps reads as a new visit, so the timeline marks it. */
const QUIET_SECONDS = 30 * 60

const isForm = (item: TimelineItem) => item.type === "event" && item.event_type === "form_submit"

function title(item: TimelineItem): string {
  if (item.type === "visit") return "Page view"
  return humanize(item.event_type) || "Event"
}

function decode(s: string): string {
  try { return decodeURIComponent(s) } catch { return s }
}

const hostOf = (url: string) => {
  try { return new URL(url).host.replace(/^www\./, "") } catch { return "" }
}

/**
 * A whole URL, never cut off: host and query muted, the path in full, wrapping wherever it has to.
 * Only http(s) addresses become links, since the tracker records whatever a page reports.
 */
export function FullUrl({ url, className, plain }: {
  url: string; className?: string
  /** Text only, for use inside another button or link */
  plain?: boolean
}) {
  let host = ""
  let path = url
  let rest = ""
  try {
    const u = new URL(url)
    host = u.host
    path = decode(u.pathname)
    rest = decode(`${u.search}${u.hash}`)
  } catch { /* not a URL; show it as given */ }
  const body = (
    <>
      {host && <span className="text-muted-foreground">{host}</span>}
      <span className="text-foreground">{path}</span>
      {rest && <span className="text-muted-foreground">{rest}</span>}
    </>
  )
  const cls = cn("font-mono text-xs leading-5 wrap-anywhere", className)
  return !plain && /^https?:\/\//i.test(url)
    ? <a href={url} target="_blank" rel="noopener noreferrer" className={cn(cls, "underline-offset-2 hover:underline")}>{body}</a>
    : <span className={cls}>{body}</span>
}

/** A referrer from another site (search, an AI assistant, a newsletter); internal hops add nothing. */
function outsideReferrer(item: TimelineItem): string | null {
  const ref = item.referrer?.trim()
  if (!ref) return null
  if (!item.page_url) return ref
  const from = hostOf(ref)
  return from && from === hostOf(item.page_url) ? null : ref
}

function EventData({ data, expanded }: { data: Record<string, unknown>; expanded: boolean }) {
  const fields = Object.keys(data).length
  const flat = Object.values(data).every((v) => v === null || typeof v !== "object")
  return (
    <Collapsible defaultOpen={expanded}>
      <CollapsibleTrigger className="group flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ChevronRight className="size-3 transition-transform group-data-[panel-open]:rotate-90" />
        Event data<span className="tabular-nums">· {fields} field{fields === 1 ? "" : "s"}</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-1.5">
        {flat ? <div className="rounded-md border px-2.5 py-0.5"><DataValue value={data} className="text-xs" /></div> : <JsonBlock value={data} />}
      </CollapsibleContent>
    </Collapsible>
  )
}

function FormSubmission({ data, expanded }: { data: Record<string, unknown>; expanded: boolean }) {
  const values = data.form_values as Record<string, unknown> | undefined
  const filled = Number(data.filled_fields ?? (values ? Object.keys(values).length : 0))
  return (
    <div className="space-y-2">
      <div className="rounded-md border border-[color-mix(in_oklch,var(--good),transparent_70%)] bg-[color-mix(in_oklch,var(--good),transparent_94%)] p-2.5">
        <div className="mb-1 flex items-center justify-between text-xs font-medium text-good">
          <span>Form submission</span>
          <span className="tabular-nums">{filled} field{filled === 1 ? "" : "s"} filled</span>
        </div>
        {values && Object.keys(values).length > 0 ? <DataValue value={values} /> : <JsonBlock value={data} />}
      </div>
      {values && Object.keys(values).length > 0 && (
        <Collapsible defaultOpen={expanded}>
          <CollapsibleTrigger className="group flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <ChevronRight className="size-3 transition-transform group-data-[panel-open]:rotate-90" />Raw event data
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-1.5"><JsonBlock value={data} /></CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}

function Entry({ item, since, rail, showVisitor, expanded }: {
  item: TimelineItem; since?: number; rail: boolean; showVisitor: boolean; expanded: boolean
}) {
  const Icon = ICONS[item.type === "visit" ? "visit" : item.event_type ?? ""] ?? Zap
  const form = isForm(item) && !!item.data
  const loc = place(item.city, item.country)
  const tracking = [item.tracking_method, item.tracking_id].filter(Boolean).join(":")
  const hasData = item.type === "event" && item.data && Object.keys(item.data).length > 0
  const referrer = outsideReferrer(item)

  return (
    <li className="group/entry relative grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 pb-5">
      {rail && <span aria-hidden className="absolute top-7 bottom-0 left-[0.8125rem] w-px bg-border" />}
      <span className={cn(
        "relative z-10 flex size-7 items-center justify-center rounded-full border bg-background text-muted-foreground [&_svg]:size-3.5",
        form && "border-[color-mix(in_oklch,var(--good),transparent_50%)] text-good",
      )}>
        <Icon />
      </span>
      <div className="min-w-0 space-y-1.5 pt-0.5">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-sm font-medium">{title(item)}</span>
          <span className="flex shrink-0 items-baseline gap-2 text-xs text-muted-foreground tabular-nums">
            {since !== undefined && <span title="Time since the step before">+{seconds(since)}</span>}
            <time className="text-foreground/80" dateTime={item.timestamp ?? undefined} title={fullTime(item.timestamp)}>
              {clockTime(item.timestamp)}
            </time>
          </span>
        </div>
        {item.page_url && (
          <div className="flex items-start gap-1">
            <FullUrl url={item.page_url} className="min-w-0" />
            <CopyButton value={item.page_url} label="Copy URL"
              className="-my-0.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/entry:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100" />
          </div>
        )}
        {referrer && (
          <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <span className="shrink-0 leading-5">from</span>
            <FullUrl url={referrer} className="min-w-0 [&_span]:text-muted-foreground" />
          </div>
        )}
        {(showVisitor && item.crawler_type) || item.source || item.medium || item.campaign || loc || tracking ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {showVisitor && item.crawler_type && <VisitorBadge label={item.crawler_type} isBot={item.is_bot} />}
            {(item.source || item.medium || item.campaign) && (
              <span className="flex min-w-0 items-start gap-1">
                <Tag className="mt-0.5 size-3 shrink-0" />
                <SourceText wrap source={item.source} medium={item.medium} campaign={item.campaign} className="text-foreground/80" />
              </span>
            )}
            {loc && <span className="flex items-center gap-1"><MapPin className="size-3" />{loc}</span>}
            {tracking && <span className="flex items-center gap-1 font-mono wrap-anywhere"><Fingerprint className="size-3 shrink-0" />{tracking}</span>}
          </div>
        ) : null}
        {form ? <FormSubmission data={item.data!} expanded={expanded} /> : hasData ? <EventData data={item.data!} expanded={expanded} /> : null}
      </div>
    </li>
  )
}

type Row =
  | { kind: "day"; key: string; label: string }
  | { kind: "gap"; key: string; secs: number }
  | { kind: "item"; key: string; item: TimelineItem; since?: number }

/** Day headings, quiet stretches and the time since the step before, worked out once per list. */
function toRows(items: TimelineItem[]): Row[] {
  const out: Row[] = []
  let day = ""
  let prev: number | undefined
  items.forEach((item, i) => {
    const t = item.timestamp ? Date.parse(item.timestamp) : Number.NaN
    const key = `${item.type}-${item.id}-${i}`
    let since: number | undefined
    if (!Number.isNaN(t)) {
      const d = new Date(t)
      const k = d.toDateString()
      const gap = prev === undefined ? undefined : (t - prev) / 1000
      if (k !== day) {
        day = k
        out.push({ kind: "day", key: `day-${i}`, label: d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" }) })
      } else if (gap !== undefined && gap >= QUIET_SECONDS) {
        out.push({ kind: "gap", key: `gap-${i}`, secs: gap })
      }
      if (gap !== undefined && gap >= 1 && gap < QUIET_SECONDS) since = gap
      prev = t
    }
    out.push({ kind: "item", key, item, since })
  })
  return out
}

/** The rail-and-dot event list used by every session, journey and user view. */
export function Timeline({ items, loading, showVisitor = true, expanded = false, empty }: {
  items: TimelineItem[] | undefined; loading?: boolean
  /** Session views already say who it is */
  showVisitor?: boolean
  /** Open every event's data instead of leaving it folded */
  expanded?: boolean
  /** What to show when there is nothing (a filter that matched nothing, say) */
  empty?: ReactNode
}) {
  const rows = useMemo(() => toRows(items ?? []), [items])

  if (loading) {
    return <div className="space-y-3 pt-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
  }
  if (!items?.length) {
    return <div className="pt-3">{empty ?? (
      <Empty className="border py-8">
        <EmptyHeader>
          <EmptyTitle>No activity yet</EmptyTitle>
          <EmptyDescription>Page views and events show up here as they are tracked.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )}</div>
  }

  return (
    <ol className="relative">
      {rows.map((row, i) => {
        if (row.kind === "day") {
          return (
            <li key={row.key} className="sticky top-0 z-20 -mx-1 flex items-center gap-3 bg-popover/95 px-1 py-3 backdrop-blur-sm">
              <span className="text-xs font-medium text-muted-foreground">{row.label}</span>
              <span aria-hidden className="h-px flex-1 bg-border" />
            </li>
          )
        }
        if (row.kind === "gap") {
          return (
            <li key={row.key} className="flex items-center gap-2 pb-5 pl-10 text-xs text-muted-foreground">
              <span aria-hidden className="w-3 border-t border-dashed" />
              {seconds(row.secs)} later
              <span aria-hidden className="flex-1 border-t border-dashed" />
            </li>
          )
        }
        return (
          <Entry key={`${row.key}-${expanded ? 1 : 0}`} item={row.item} since={row.since} rail={rows[i + 1]?.kind === "item"}
            showVisitor={showVisitor} expanded={expanded} />
        )
      })}
    </ol>
  )
}

/* ---------- Filtering a long timeline ---------- */

type Kind = "all" | "visit" | "event" | "form"

function matches(item: TimelineItem, q: string): boolean {
  const hay = [title(item), item.event_type, item.page_url, item.referrer, item.source, item.medium, item.campaign, item.crawler_type]
    .filter(Boolean).join(" ").toLowerCase()
  if (hay.includes(q)) return true
  return !!item.data && JSON.stringify(item.data).toLowerCase().includes(q)
}

/** Which kinds of step to show, a text filter and whether event data starts open. */
export function useActivityFilter(items: TimelineItem[] | undefined) {
  const [kind, setKind] = useState<Kind>("all")
  const [query, setQuery] = useState("")
  const [expanded, setExpanded] = useState(false)

  const counts = useMemo(() => {
    const c = { all: 0, visit: 0, event: 0, form: 0 }
    for (const i of items ?? []) {
      c.all++
      if (i.type === "visit") c.visit++
      else c.event++
      if (isForm(i)) c.form++
    }
    return c
  }, [items])

  const q = query.trim().toLowerCase()
  const shown = useMemo(() => items?.filter((i) =>
    (kind === "all" || (kind === "form" ? isForm(i) : i.type === kind)) && (!q || matches(i, q)),
  ), [items, kind, q])

  return {
    kind, setKind, query, setQuery, expanded, setExpanded, counts, shown, loaded: items !== undefined,
    filtered: kind !== "all" || !!q,
    clear: () => { setKind("all"); setQuery("") },
  }
}

export type ActivityFilter = ReturnType<typeof useActivityFilter>

const KINDS: { value: Kind; label: string }[] = [
  { value: "all", label: "All" }, { value: "visit", label: "Page views" }, { value: "event", label: "Events" }, { value: "form", label: "Forms" },
]

export function ActivityToolbar({ filter: f }: { filter: ActivityFilter }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <ToggleGroup variant="outline" size="sm" spacing={0} aria-label="Show"
        value={[f.kind]} onValueChange={(v) => { const n = (v as string[])[0]; if (n) f.setKind(n as Kind) }}>
        {KINDS.filter((k) => k.value !== "form" || f.counts.form > 0).map((k) => (
          <ToggleGroupItem key={k.value} value={k.value} className="gap-1.5 px-2.5">
            {k.label}{f.loaded && <span className="text-muted-foreground tabular-nums">{num(f.counts[k.value])}</span>}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <SearchInput value={f.query} onChange={f.setQuery} placeholder="Filter steps by URL or value" debounce={150} className="w-64 max-w-full" />
      <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-muted-foreground select-none">
        <Switch size="sm" checked={f.expanded} onCheckedChange={f.setExpanded} />Expand event data
      </label>
    </div>
  )
}

/** Shown in place of the timeline when the filter matches nothing. */
export function NoMatches({ onClear }: { onClear: () => void }) {
  return (
    <Empty className="border py-8">
      <EmptyHeader>
        <EmptyTitle>Nothing matches</EmptyTitle>
        <EmptyDescription>
          No step here matches this filter. <button type="button" className="underline underline-offset-3 hover:text-foreground" onClick={onClear}>Show everything</button>
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}
