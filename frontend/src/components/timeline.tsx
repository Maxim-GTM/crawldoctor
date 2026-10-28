import { ChevronRight, Eye, FileCheck2, Fingerprint, MapPin, MousePointerClick, Navigation, Tag, Zap } from "lucide-react"

import { DataValue, JsonBlock } from "@/components/data-value"
import { SourceText, VisitorBadge } from "@/components/visitor-badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import type { TimelineItem } from "@/lib/api"
import { fullTime, humanize, place, splitUrl } from "@/lib/format"
import { cn } from "@/lib/utils"

const ICONS: Record<string, typeof Eye> = {
  visit: Eye, page_view: Eye, click: MousePointerClick, form_submit: FileCheck2, navigation: Navigation,
}

function title(item: TimelineItem): string {
  if (item.type === "visit") return "Page view"
  return humanize(item.event_type) || "Event"
}

function PageLink({ url }: { url: string }) {
  const { host, path } = splitUrl(url)
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="group/link block min-w-0 truncate text-sm" title={url}>
      <span className="text-foreground group-hover/link:underline">{path}</span>
      {host && <span className="text-muted-foreground"> · {host}</span>}
    </a>
  )
}

function FormSubmission({ data }: { data: Record<string, unknown> }) {
  const values = data.form_values as Record<string, unknown> | undefined
  const filled = Number(data.filled_fields ?? (values ? Object.keys(values).length : 0))
  return (
    <div className="rounded-md border border-[color-mix(in_oklch,var(--good),transparent_70%)] bg-[color-mix(in_oklch,var(--good),transparent_94%)] p-2.5">
      <div className="mb-1 flex items-center justify-between text-xs font-medium text-good">
        <span>Form submission</span>
        <span className="tabular-nums">{filled} field{filled === 1 ? "" : "s"} filled</span>
      </div>
      {values && Object.keys(values).length > 0 ? <DataValue value={values} /> : <JsonBlock value={data} />}
    </div>
  )
}

/** The rail-and-dot event list used by every session, journey and user panel. */
export function Timeline({ items, loading, showVisitor = true }: {
  items: TimelineItem[] | undefined; loading?: boolean
  /** Session panels already say who it is */
  showVisitor?: boolean
}) {
  if (loading) {
    return <div className="space-y-3">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>
  }
  if (!items?.length) {
    return (
      <Empty className="border py-8">
        <EmptyHeader>
          <EmptyTitle>No activity yet</EmptyTitle>
          <EmptyDescription>Page views and events show up here as they are tracked.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  return (
    <ol className="relative">
      {items.map((item, i) => {
        const Icon = ICONS[item.type === "visit" ? "visit" : item.event_type ?? ""] ?? Zap
        const isForm = item.type === "event" && item.event_type === "form_submit" && item.data
        const loc = place(item.city, item.country)
        const tracking = [item.tracking_method, item.tracking_id].filter(Boolean).join(":")
        const hasData = item.type === "event" && item.data && Object.keys(item.data).length > 0
        return (
          <li key={`${item.type}-${item.id}-${i}`} className="relative grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 pb-4 last:pb-0">
            {i < items.length - 1 && <span aria-hidden className="absolute top-7 bottom-0 left-[0.8125rem] w-px bg-border" />}
            <span className={cn(
              "relative z-10 flex size-7 items-center justify-center rounded-full border bg-background text-muted-foreground [&_svg]:size-3.5",
              isForm && "border-[color-mix(in_oklch,var(--good),transparent_50%)] text-good",
            )}>
              <Icon />
            </span>
            <div className="min-w-0 space-y-1.5 pt-0.5">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-sm font-medium">{title(item)}</span>
                <time className="shrink-0 text-xs text-muted-foreground tabular-nums" dateTime={item.timestamp ?? undefined}>
                  {fullTime(item.timestamp)}
                </time>
              </div>
              {item.page_url && <PageLink url={item.page_url} />}
              {(showVisitor && item.crawler_type) || item.source || item.medium || item.campaign || loc || tracking ? (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  {showVisitor && item.crawler_type && <VisitorBadge label={item.crawler_type} isBot={item.is_bot} />}
                  {(item.source || item.medium || item.campaign) && (
                    <span className="flex min-w-0 items-center gap-1"><Tag className="size-3 shrink-0" /><SourceText source={item.source} medium={item.medium} campaign={item.campaign} className="text-foreground/80" /></span>
                  )}
                  {loc && <span className="flex items-center gap-1"><MapPin className="size-3" />{loc}</span>}
                  {tracking && <span className="flex items-center gap-1 font-mono"><Fingerprint className="size-3" />{tracking}</span>}
                </div>
              ) : null}
              {isForm ? (
                <FormSubmission data={item.data!} />
              ) : hasData ? (
                <Collapsible>
                  <CollapsibleTrigger className="group flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                    <ChevronRight className="size-3 transition-transform group-data-[panel-open]:rotate-90" />Event data
                  </CollapsibleTrigger>
                  <CollapsibleContent className="pt-1.5"><JsonBlock value={item.data} /></CollapsibleContent>
                </Collapsible>
              ) : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
