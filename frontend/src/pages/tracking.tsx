import { useQuery } from "@tanstack/react-query"
import { CircleAlert, CircleCheck, CircleDashed, RadioTower } from "lucide-react"

import { FilterSwitch } from "@/components/filters"
import { Page, PageHeader } from "@/components/page-header"
import { EmptyRow, LoadingRows } from "@/components/table-state"
import { useUrlFilters } from "@/hooks/use-url-filters"
import { Badge } from "@/components/ui/badge"
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { analyticsAPI, apiError, type TrackingStatus } from "@/lib/api"
import { fullTime, num, relativeTime, shortDate } from "@/lib/format"
import { describe } from "@/lib/nav"
import { cn } from "@/lib/utils"

const STATUS: Record<TrackingStatus, { label: string; icon: typeof CircleCheck; className: string; help: string }> = {
  live: { label: "Live", icon: CircleCheck, className: "text-good", help: "A page view in the last 24 hours" },
  quiet: { label: "Quiet", icon: CircleDashed, className: "text-[var(--series-4)]", help: "No page view for a day, but one this week" },
  stale: { label: "Silent", icon: CircleAlert, className: "text-bad", help: "No page view for over a week" },
}

function StatusBadge({ status, since }: { status: TrackingStatus; since?: string | null }) {
  const s = STATUS[status]
  return (
    <Badge variant="outline" className={cn("gap-1 font-normal", s.className)} title={s.help}>
      <s.icon />{s.label}{status === "stale" && since ? <span className="text-muted-foreground">since {shortDate(since)}</span> : null}
    </Badge>
  )
}

const FILTERS = { others: "", retired: "" }
// A host that hasn't sent a page view for this long was moved or retired, not broken
const RETIRED_MS = 90 * 86_400_000
const retired = (lastSeen?: string | null) => !lastSeen || Date.now() - new Date(lastSeen).getTime() > RETIRED_MS

export function TrackingPage() {
  const { filters: f, set } = useUrlFilters(FILTERS)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["tracking-health"], queryFn: analyticsAPI.getTrackingHealth, refetchInterval: 5 * 60_000,
  })
  const all = data?.sites ?? []
  const sites = all.filter((s) => (s.ours || f.others) && (f.retired || !retired(s.last_seen)))
  const others = all.filter((s) => !s.ours && (f.retired || !retired(s.last_seen))).length
  const retiredCount = all.filter((s) => (s.ours || f.others) && retired(s.last_seen)).length
  const ours = all.filter((s) => s.ours && !retired(s.last_seen))
  const count = (st: TrackingStatus) => ours.filter((s) => s.status === st).length

  return (
    <>
      <PageHeader title="Tracking health" description={describe("/site-health")} />
      <Page>
        <div className="grid gap-3 sm:grid-cols-3">
          {(["live", "quiet", "stale"] as const).map((st) => {
            const S = STATUS[st]
            return (
              <Card key={st} className="gap-1 py-4">
                <CardHeader className="gap-1 px-4">
                  <CardDescription className={cn("flex items-center gap-2 [&_svg]:size-4", S.className)}><S.icon />{S.label}</CardDescription>
                  <CardTitle className="text-2xl font-semibold tabular-nums">{data ? num(count(st)) : "–"}</CardTitle>
                  <div className="text-xs text-muted-foreground">{S.help}</div>
                </CardHeader>
              </Card>
            )
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <FilterSwitch label={`Show other hosts${others ? ` (${num(others)})` : ""}`} checked={!!f.others} onChange={(v) => set({ others: v ? "1" : "" })} />
          <FilterSwitch label={`Show hosts silent for 90+ days${retiredCount && !f.retired ? ` (${num(retiredCount)})` : ""}`}
            checked={!!f.retired} onChange={(v) => set({ retired: v ? "1" : "" })} />
          <span className="ml-auto text-xs text-muted-foreground">
            {data && <>Checked {relativeTime(data.checked_at)}{data.hidden_domains ? ` · ${num(data.hidden_domains)} local, test and IP hosts hidden` : ""}</>}
          </span>
        </div>

        <Card className="overflow-hidden py-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Site</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last page view</TableHead>
                  <TableHead className="text-right">24 hours</TableHead>
                  <TableHead className="text-right">7 days</TableHead>
                  <TableHead>Tracking IDs (30 days)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && <LoadingRows cols={6} rows={6} />}
                {isError && <EmptyRow cols={6} error title="Couldn't check tracking" description={apiError(error)} />}
                {data && sites.length === 0 && <EmptyRow cols={6} icon={<RadioTower />} title="No tracked sites yet" />}
                {sites.map((s) => (
                  <TableRow key={s.domain} className={cn("align-top", s.status === "stale" && s.ours && "bg-[color-mix(in_oklch,var(--bad),transparent_95%)]")}>
                    <TableCell className="font-medium">
                      {s.domain}
                      {!s.ours && <div className="text-xs font-normal text-muted-foreground">Not one of our domains</div>}
                    </TableCell>
                    <TableCell><StatusBadge status={s.status} since={s.last_seen} /></TableCell>
                    <TableCell className="tabular-nums" title={fullTime(s.last_seen)}>{relativeTime(s.last_seen)}</TableCell>
                    <TableCell className="text-right tabular-nums">{num(s.views_24h)}</TableCell>
                    <TableCell className="text-right tabular-nums">{num(s.views_7d)}</TableCell>
                    <TableCell className="whitespace-normal">
                      {s.tracking_ids.length ? (
                        <div className="flex flex-wrap gap-1">
                          {s.tracking_ids.map((t) => (
                            <Badge key={t.tracking_id ?? "none"} variant="outline" className="gap-1.5 font-normal" title={`${STATUS[t.status].label} · last ${fullTime(t.last_seen)}`}>
                              <span className={cn("size-1.5 rounded-full bg-current", STATUS[t.status].className)} />
                              <span className="font-mono">{t.tracking_id ?? "no ID"}</span>
                              <span className="text-muted-foreground tabular-nums">{num(t.views_30d)}</span>
                            </Badge>
                          ))}
                        </div>
                      ) : <span className="text-xs text-muted-foreground">None in 30 days</span>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Card>
      </Page>
    </>
  )
}
