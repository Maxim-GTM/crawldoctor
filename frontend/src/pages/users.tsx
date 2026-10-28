import { useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { ChevronRight, FileCheck2, Users } from "lucide-react"

import { ShortId } from "@/components/client-id"
import { DataPagination } from "@/components/data-pagination"
import { DateRangePicker } from "@/components/date-range-picker"
import { DetailSheet, type Detail } from "@/components/detail-sheet"
import {
  ClearFilters, FilterBar, FilterSelect, FilterSwitch, ResultCount, SearchInput, SuggestInput, VISITOR_OPTIONS, useFacet,
} from "@/components/filters"
import { Page, PageHeader } from "@/components/page-header"
import { EmptyRow, LoadingRows } from "@/components/table-state"
import { SourceText } from "@/components/visitor-badge"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useDateRange } from "@/hooks/use-date-range"
import { usePage, useUrlFilters } from "@/hooks/use-url-filters"
import { analyticsAPI, apiError } from "@/lib/api"
import { fullTime, num, plural, relativeTime, shortDate } from "@/lib/format"
import { describe } from "@/lib/nav"

// Bots get client IDs too (GoogleBot alone is most of them), so the list starts with people
const FILTERS = { q: "", visitor: "human", converted: "", source: "" }

export function UsersPage() {
  const [range, setRange] = useDateRange(30)
  const { filters: f, set, clear, active } = useUrlFilters(FILTERS)
  const [page, setPage] = usePage(JSON.stringify([range, f]))
  const [size, setSize] = useState(20)
  const [detail, setDetail] = useState<Detail | null>(null)
  const query = { q: f.q.trim() || undefined, visitor: f.visitor === "all" ? undefined : f.visitor, converted: f.converted === "1", source: f.source.trim() || undefined }
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["unified-users", range, query, page, size], queryFn: () => analyticsAPI.listUnifiedUsers(range, query, size, (page - 1) * size),
    refetchInterval: 60_000, placeholderData: keepPreviousData,
  })
  const sources = useFacet("visits.source", range, true)

  return (
    <>
      <PageHeader title="Users" description={describe("/users")}>
        <DateRangePicker value={range} onChange={setRange} />
      </PageHeader>
      <Page>
        <FilterBar>
          <SearchInput label="Search by client ID, email or name" placeholder="Client ID, email or name" className="max-w-72"
            value={f.q} onChange={(q) => set({ q })} />
          <FilterSelect label="Visitor type" allLabel="Humans and bots" value={f.visitor === "all" ? "" : f.visitor}
            onChange={(v) => set({ visitor: v || "all" })} options={VISITOR_OPTIONS} defaultValue={FILTERS.visitor} />
          <SuggestInput label="Arrived from a source containing" placeholder="Source" value={f.source} onChange={(source) => set({ source })}
            suggestions={sources.map((v) => v.value)} />
          <FilterSwitch label="Submitted a form" checked={f.converted === "1"} onChange={(v) => set({ converted: v ? "1" : "" })} />
          <ClearFilters active={active} onClear={clear} />
          <ResultCount count={data?.total_count} noun={f.visitor === "human" ? "people active in this range" : "users active in this range"} loading={isLoading} />
        </FilterBar>
        <Card className="overflow-hidden py-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>First touch</TableHead>
                  <TableHead>Campaign</TableHead>
                  <TableHead>Activity</TableHead>
                  <TableHead>First seen</TableHead>
                  <TableHead>Last seen</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && <LoadingRows cols={7} />}
                {(isError || data?.error) && <EmptyRow cols={7} error title="Couldn't load users" description={data?.error ?? apiError(error)} />}
                {data && !data.error && data.users.length === 0 && (
                  <EmptyRow cols={7} icon={<Users />} title={active ? "No users match" : "No users in this range"}
                    description={active ? "Clear a filter or pick a wider date range." : "Visitors with a persistent client ID appear here."} />
                )}
                {data?.users.map((u) => (
                  <TableRow key={u.client_id} className="cursor-pointer" onClick={() => setDetail({ kind: "user", id: u.client_id })}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {u.name || u.email ? (
                          <div className="min-w-0">
                            <div className="max-w-56 truncate font-medium">{u.name || u.email}</div>
                            <div className="max-w-56 truncate text-xs text-muted-foreground">{u.name && u.email ? u.email : <ShortId id={u.client_id} />}</div>
                          </div>
                        ) : <ShortId id={u.client_id} length={12} />}
                        {u.conversion_count > 0 && (
                          <Badge variant="outline" className="gap-1 font-normal text-good"><FileCheck2 />{plural(u.conversion_count, "lead")}</Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-48"><SourceText source={u.attribution?.source} medium={u.attribution?.medium} className="block" /></TableCell>
                    <TableCell className="max-w-48 truncate text-muted-foreground" title={u.attribution?.campaign}>{u.attribution?.campaign || "—"}</TableCell>
                    <TableCell className="tabular-nums">
                      {plural(u.session_count, "session")}
                      <span className="text-muted-foreground"> · {num(u.visit_count)} views</span>
                    </TableCell>
                    <TableCell className="text-muted-foreground tabular-nums">{shortDate(u.first_seen)}</TableCell>
                    <TableCell className="tabular-nums" title={fullTime(u.last_seen)}>{relativeTime(u.last_seen)}</TableCell>
                    <TableCell><ChevronRight className="size-4 text-muted-foreground" /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <DataPagination data={data} page={page} pageSize={size} onPage={setPage} onPageSize={setSize} />
        </Card>
      </Page>
      <DetailSheet detail={detail} onChange={setDetail} />
    </>
  )
}
