import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { ArrowRight, Waypoints } from "lucide-react"
import { Link } from "react-router-dom"

import { DateRangePicker } from "@/components/date-range-picker"
import { Page, PageHeader } from "@/components/page-header"
import { EmptyRow, LoadingRows } from "@/components/table-state"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useDateRange } from "@/hooks/use-date-range"
import { analyticsAPI, apiError } from "@/lib/api"
import { num, pct } from "@/lib/format"
import { describe } from "@/lib/nav"

/** One colour per channel, from the hub's series palette. */
export const CHANNEL_COLORS: Record<string, string> = {
  Search: "var(--series-3)", "AI assistants": "var(--series-2)", Social: "var(--series-5)", Referral: "var(--series-7)",
  Paid: "var(--series-4)", Direct: "var(--series-1)", Internal: "var(--series-gray)",
}

const CHANNEL_HELP: Record<string, string> = {
  Search: "Google, Bing, DuckDuckGo and other search engines, organic",
  "AI assistants": "ChatGPT, Perplexity, Claude, Gemini, Copilot and other assistants",
  Social: "LinkedIn, X, Reddit, YouTube, Hacker News…",
  Referral: "Links from other sites, newsletters and anything not covered above",
  Paid: "Ads: a cpc, ppc, paid or display utm_medium",
  Direct: "No referrer and no utm_source",
  Internal: "Moves between our own sites (getmaxim.ai, getbifrost.ai) and our docs links",
}

export function ChannelsPage() {
  const [range, setRange] = useDateRange(30)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["channels", range], queryFn: () => analyticsAPI.getChannels(range), placeholderData: keepPreviousData,
  })
  const channels = data?.channels ?? []
  const views = channels.reduce((a, c) => a + c.views, 0)
  const leads = channels.reduce((a, c) => a + c.leads, 0)
  // Self-referrals inflate "views from a source"; the mix reads better without them
  const external = channels.filter((c) => c.channel !== "Internal")
  const externalViews = external.reduce((a, c) => a + c.views, 0)

  return (
    <>
      <PageHeader title="Channels" description={describe("/channels")}>
        <DateRangePicker value={range} onChange={setRange} />
      </PageHeader>
      <Page>
        <Card>
          <CardHeader>
            <CardTitle>Traffic mix</CardTitle>
            <CardDescription>Human page views by channel, leaving out moves between our own sites</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {isLoading ? <Skeleton className="h-3 rounded-full" /> : (
              <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full bg-muted">
                {external.map((c) => (
                  <div key={c.channel} className="h-full first:rounded-l-full last:rounded-r-full" title={`${c.channel}: ${num(c.views)}`}
                    style={{ width: `${(c.views / Math.max(1, externalViews)) * 100}%`, background: CHANNEL_COLORS[c.channel] }} />
                ))}
              </div>
            )}
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-6">
              {external.map((c) => (
                <div key={c.channel} className="space-y-0.5">
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span className="size-2 rounded-full" style={{ background: CHANNEL_COLORS[c.channel] }} />{c.channel}
                  </div>
                  <div className="flex items-baseline gap-1.5">
                    <span className="text-lg font-semibold tabular-nums">{num(c.views)}</span>
                    <span className="text-xs text-muted-foreground tabular-nums">{pct(c.views, externalViews)}</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="overflow-hidden py-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Channel</TableHead>
                  <TableHead className="text-right">Page views</TableHead>
                  <TableHead className="text-right">People</TableHead>
                  <TableHead className="text-right">Leads</TableHead>
                  <TableHead>Top sources</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && <LoadingRows cols={5} rows={6} />}
                {isError && <EmptyRow cols={5} error title="Couldn't load channels" description={apiError(error)} />}
                {data && channels.length === 0 && <EmptyRow cols={5} icon={<Waypoints />} title="No human traffic in this range" />}
                {channels.map((c) => (
                  <TableRow key={c.channel} className="align-top">
                    <TableCell>
                      <div className="flex items-center gap-2 font-medium">
                        <span className="size-2.5 rounded-full" style={{ background: CHANNEL_COLORS[c.channel] }} />{c.channel}
                      </div>
                      <div className="mt-0.5 max-w-64 text-xs whitespace-normal text-muted-foreground">{CHANNEL_HELP[c.channel]}</div>
                      {c.channel === "AI assistants" && (
                        <Button variant="link" size="xs" className="-ml-1.5 h-6" nativeButton={false}
                          render={<Link to={`/ai-referrals?from=${range.start}&to=${range.end}`} />}>AI referrals report<ArrowRight /></Button>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      <div className="font-medium">{num(c.views)}</div>
                      <div className="text-xs text-muted-foreground">{pct(c.views, views)}</div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{num(c.visitors)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      <div className="font-medium">{num(c.leads)}</div>
                      {leads > 0 && <div className="text-xs text-muted-foreground">{pct(c.leads, leads)}</div>}
                    </TableCell>
                    <TableCell className="whitespace-normal">
                      <div className="flex max-w-xl flex-wrap gap-1">
                        {c.sources.map((s) => (
                          <Badge key={`${s.source}/${s.medium}`} variant="outline" className="gap-1 font-normal">
                            <span className="max-w-48 truncate">{s.source}{s.medium ? <span className="text-muted-foreground"> / {s.medium}</span> : null}</span>
                            <span className="text-muted-foreground tabular-nums">{num(s.views)}</span>
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Card>
        <p className="text-xs text-muted-foreground">
          Bots are left out. A page view counts toward the channel of its own source, so one person can appear under several channels;
          leads count by their first touch.
        </p>
      </Page>
    </>
  )
}
