import { Fragment, useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Building2, ChevronRight, Info } from "lucide-react"

import { DateRangePicker } from "@/components/date-range-picker"
import { countryName } from "@/components/filters"
import { Page, PageHeader } from "@/components/page-header"
import { EmptyRow, LoadingRows } from "@/components/table-state"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useDateRange } from "@/hooks/use-date-range"
import { analyticsAPI, apiError } from "@/lib/api"
import { fullTime, humanize, num, pct, relativeTime } from "@/lib/format"
import { describe } from "@/lib/nav"
import { cn } from "@/lib/utils"

export function CompaniesPage() {
  const [range, setRange] = useDateRange(30)
  const [open, setOpen] = useState<string | null>(null)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["companies", range], queryFn: () => analyticsAPI.getCompanies(range), placeholderData: keepPreviousData,
  })
  const c = data?.coverage
  const enriched = c ? c.enriched_sessions / Math.max(1, c.human_sessions) : 0

  return (
    <>
      <PageHeader title="Companies" description={describe("/companies")}>
        <DateRangePicker value={range} onChange={setRange} />
      </PageHeader>
      <Page>
        {/* Say plainly how little of the traffic this covers before showing any company */}
        <Alert>
          <Info />
          <AlertTitle>
            {c ? `${pct(c.company_sessions, c.human_sessions)} of human sessions are tied to a company` : "Checking how much traffic has an IP lookup…"}
          </AlertTitle>
          <AlertDescription className="space-y-2">
            {c && (
              <>
                <p>
                  {num(c.enriched_sessions)} of {num(c.human_sessions)} human sessions in this range ({pct(c.enriched_sessions, c.human_sessions)}) have an IP lookup.
                  {c.detailed_sessions < c.enriched_sessions && <> {num(c.enriched_sessions - c.detailed_sessions)} of those lookups have just a name,
                    which can't tell an employer from a home ISP or cloud host.</>}
                  {" "}Of the {num(c.detailed_sessions)} with company details, {num(c.company_sessions)} come from an organisation;
                  the rest are home ISPs, cloud hosts, VPNs or proxies.
                  The lookup job is being repaired, so treat this list as a sample, not a full account of who visited.
                </p>
                <Progress value={Math.min(100, enriched * 100)} className="h-1.5 max-w-md" aria-label="Sessions with an IP lookup" />
              </>
            )}
          </AlertDescription>
        </Alert>

        <Card className="overflow-hidden py-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8" />
                  <TableHead>Company</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Country</TableHead>
                  <TableHead className="text-right">Page views</TableHead>
                  <TableHead className="text-right">Sessions</TableHead>
                  <TableHead className="text-right">People</TableHead>
                  <TableHead>Last seen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && <LoadingRows cols={8} />}
                {isError && <EmptyRow cols={8} error title="Couldn't load companies" description={apiError(error)} />}
                {data && data.companies.length === 0 && (
                  <EmptyRow cols={8} icon={<Building2 />} title="No companies identified in this range"
                    description="Either no visits came from an organisation's network, or their IPs haven't been looked up yet." />
                )}
                {data?.companies.map((co) => {
                  const expanded = open === co.domain
                  return (
                    <Fragment key={co.domain}>
                      <TableRow className="cursor-pointer" data-state={expanded ? "selected" : undefined} aria-expanded={expanded}
                        onClick={() => setOpen(expanded ? null : co.domain)}>
                        <TableCell className="pr-0"><ChevronRight className={cn("size-4 text-muted-foreground transition-transform", expanded && "rotate-90")} /></TableCell>
                        <TableCell className="max-w-72">
                          <div className="truncate font-medium">{co.name || co.domain}</div>
                          <a href={`https://${co.domain}`} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
                            className="truncate text-xs text-muted-foreground hover:underline">{co.domain}</a>
                        </TableCell>
                        <TableCell>{co.type ? <Badge variant="outline" className="font-normal">{humanize(co.type)}</Badge> : "—"}</TableCell>
                        <TableCell className="text-muted-foreground">{co.country ? countryName(co.country) : "—"}</TableCell>
                        <TableCell className="text-right font-medium tabular-nums">{num(co.views)}</TableCell>
                        <TableCell className="text-right tabular-nums">{num(co.sessions)}</TableCell>
                        <TableCell className="text-right tabular-nums">{num(co.visitors)}</TableCell>
                        <TableCell className="tabular-nums" title={fullTime(co.last_seen)}>{relativeTime(co.last_seen)}</TableCell>
                      </TableRow>
                      {expanded && (
                        <TableRow className="hover:bg-transparent">
                          <TableCell />
                          <TableCell colSpan={7} className="whitespace-normal">
                            <div className="mb-1.5 text-xs font-medium text-muted-foreground">Pages viewed</div>
                            <ul className="grid gap-1 sm:grid-cols-2">
                              {co.pages.map((p) => (
                                <li key={`${p.domain}${p.path}`} className="flex items-center justify-between gap-3 rounded-md border px-2.5 py-1.5 text-xs">
                                  <span className="min-w-0 truncate"><span className="font-mono">{p.path}</span><span className="text-muted-foreground"> · {p.domain}</span></span>
                                  <span className="shrink-0 font-medium tabular-nums">{num(p.views)}</span>
                                </li>
                              ))}
                            </ul>
                          </TableCell>
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
    </>
  )
}
