import { useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { ChevronRight, History, Route } from "lucide-react"

import { ShortId } from "@/components/client-id"
import { DataPagination } from "@/components/data-pagination"
import { DateRangePicker } from "@/components/date-range-picker"
import { DetailSheet, type Detail } from "@/components/detail-sheet"
import {
  ClearFilters, FilterBar, FilterSelect, ResultCount, SuggestInput, VISITOR_OPTIONS, countryName, useFacet,
} from "@/components/filters"
import { Page, PageHeader } from "@/components/page-header"
import { EmptyRow, LoadingRows } from "@/components/table-state"
import { SessionKind } from "@/components/visitor-badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useDateRange } from "@/hooks/use-date-range"
import { usePage, useUrlFilters } from "@/hooks/use-url-filters"
import { analyticsAPI, apiError } from "@/lib/api"
import { fullTime, num, place, relativeTime, seconds } from "@/lib/format"
import { describe } from "@/lib/nav"

const FILTERS = { visitor: "", country: "", referrer: "", cid: "" }

export function SessionsPage() {
  const [range, setRange] = useDateRange(7)
  const { filters: f, set, clear, active } = useUrlFilters(FILTERS)
  const [page, setPage] = usePage(JSON.stringify([range, f]))
  const [size, setSize] = useState(20)
  const [detail, setDetail] = useState<Detail | null>(null)
  const query = { visitor: f.visitor || undefined, country: f.country || undefined, referrer: f.referrer || undefined,
    hasClientId: f.cid === "yes" ? true : f.cid === "no" ? false : undefined }
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["sessions", range, query, page, size], queryFn: () => analyticsAPI.listSessions(range, query, size, (page - 1) * size),
    refetchInterval: 60_000, placeholderData: keepPreviousData,
  })
  const countries = useFacet("sessions.country", range)
  const referrers = useFacet("sessions.entry_referrer_domain", range)

  return (
    <>
      <PageHeader title="Sessions" description={describe("/sessions")}>
        <DateRangePicker value={range} onChange={setRange} />
      </PageHeader>
      <Page>
        <FilterBar>
          <FilterSelect label="Visitor type" allLabel="Humans and bots" value={f.visitor} onChange={(visitor) => set({ visitor })} options={VISITOR_OPTIONS} />
          <FilterSelect label="Country" allLabel="All countries" value={f.country} onChange={(country) => set({ country })}
            options={countries.map((c) => ({ value: c.value, label: countryName(c.value), count: c.count }))} />
          <SuggestInput label="Entry referrer contains" placeholder="Referrer, or “direct”" className="w-48" value={f.referrer}
            onChange={(referrer) => set({ referrer })} suggestions={["direct", ...referrers.map((r) => r.value)]} />
          <FilterSelect label="Client ID" allLabel="With or without client ID" value={f.cid} onChange={(cid) => set({ cid })}
            options={[{ value: "yes", label: "Has a client ID" }, { value: "no", label: "No client ID" }]} />
          <ClearFilters active={active} onClear={clear} />
          <ResultCount count={data?.total_count} noun="sessions" loading={isLoading} />
        </FilterBar>
        <Card className="overflow-hidden py-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Session</TableHead>
                  <TableHead>Visitor</TableHead>
                  <TableHead className="text-right">Views</TableHead>
                  <TableHead>Length</TableHead>
                  <TableHead>Location</TableHead>
                  <TableHead>Device</TableHead>
                  <TableHead>Last active</TableHead>
                  <TableHead className="w-24"><span className="sr-only">Journey</span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && <LoadingRows cols={8} />}
                {(isError || data?.error) && <EmptyRow cols={8} error title="Couldn't load sessions" description={data?.error ?? apiError(error)} />}
                {data && !data.error && data.sessions.length === 0 && (
                  <EmptyRow cols={8} icon={<History />} title={active ? "No sessions match" : "No sessions in this range"}
                    description={active ? "Clear a filter or pick a wider date range." : "Sessions start when the tracking script sees a visit."} />
                )}
                {data?.sessions.map((s) => {
                  const length = s.first_visit && s.last_visit ? (new Date(s.last_visit).getTime() - new Date(s.first_visit).getTime()) / 1000 : null
                  const device = [s.client_side_language, s.client_side_screen_resolution, s.client_side_timezone].filter(Boolean)
                  return (
                    <TableRow key={s.session_id} className="cursor-pointer" onClick={() => setDetail({ kind: "session", id: s.session_id })}>
                      <TableCell><ShortId id={s.session_id} /></TableCell>
                      <TableCell><SessionKind classification={s.classification} /></TableCell>
                      <TableCell className="text-right font-medium tabular-nums">{num(s.visit_count)}</TableCell>
                      <TableCell className="text-muted-foreground tabular-nums">{length !== null && length > 0 ? seconds(length) : "—"}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {place(s.city, s.country) || "—"}
                        {s.entry_referrer_domain && <div className="max-w-44 truncate text-xs" title={`Arrived from ${s.entry_referrer_domain}`}>from {s.entry_referrer_domain}</div>}
                      </TableCell>
                      <TableCell className="max-w-56 truncate text-xs text-muted-foreground" title={device.join(" · ")}>{device.join(" · ") || "—"}</TableCell>
                      <TableCell className="tabular-nums" title={`${fullTime(s.first_visit)} → ${fullTime(s.last_visit)}`}>{relativeTime(s.last_visit)}</TableCell>
                      <TableCell className="text-right">
                        {s.client_id ? (
                          <Button variant="ghost" size="xs" className="text-muted-foreground" title="Open this visitor's journey"
                            onClick={(e) => { e.stopPropagation(); setDetail({ kind: "journey", id: s.client_id! }) }}>
                            <Route />Journey
                          </Button>
                        ) : <ChevronRight className="ml-auto size-4 text-muted-foreground" />}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
          <DataPagination data={data} page={page} pageSize={size} onPage={setPage} onPageSize={setSize} approximate />
        </Card>
      </Page>
      <DetailSheet detail={detail} onChange={setDetail} />
    </>
  )
}
