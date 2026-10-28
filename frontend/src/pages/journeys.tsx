import { useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { ArrowDown, ArrowRight, ArrowUp, ChevronRight, Download, FileCheck2, Loader2, Route } from "lucide-react"
import { toast } from "sonner"

import { ShortId } from "@/components/client-id"
import { DataPagination } from "@/components/data-pagination"
import { DateRangePicker } from "@/components/date-range-picker"
import { DetailSheet, type Detail } from "@/components/detail-sheet"
import { ClearFilters, FilterBar, FilterSelect, FilterSwitch, ResultCount, SearchInput, useFacet } from "@/components/filters"
import { Page, PageHeader } from "@/components/page-header"
import { EmptyRow, LoadingRows } from "@/components/table-state"
import { SourceText } from "@/components/visitor-badge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useDateRange } from "@/hooks/use-date-range"
import { usePage, useUrlFilters } from "@/hooks/use-url-filters"
import { analyticsAPI, apiError, saveBlob, type JourneySort } from "@/lib/api"
import { plural, relativeTime, shortDate, stripOrigin } from "@/lib/format"
import { describe } from "@/lib/nav"
import { cn } from "@/lib/utils"

const FILTERS = { path: "", forms: "1", source: "", campaign: "", sort: "last_seen", order: "desc" }

export function JourneysPage() {
  const [range, setRange] = useDateRange(30)
  const { filters: f, set, clear, active } = useUrlFilters(FILTERS)
  const targetPath = f.path.trim()
  const [page, setPage] = usePage(JSON.stringify([range, f]))
  const [size, setSize] = useState(20)
  const [exporting, setExporting] = useState(false)
  const [detail, setDetail] = useState<Detail | null>(null)
  const sources = useFacet("journeys.source", range)
  const campaigns = useFacet("journeys.campaign", range)

  const filters = {
    targetPath: targetPath || undefined, withCapturedOnly: f.forms === "1", source: f.source || undefined, campaign: f.campaign || undefined,
    sort: f.sort as JourneySort, order: f.order as "asc" | "desc", ...range,
  }
  const sortBy = (sort: JourneySort) => set({ sort, order: f.sort === sort && f.order === "desc" ? "asc" : "desc" })
  const sortHead = (sort: JourneySort, label: string, className?: string) => (
    <TableHead className={className} aria-sort={f.sort === sort ? (f.order === "asc" ? "ascending" : "descending") : undefined}>
      <button type="button" onClick={() => sortBy(sort)}
        className={cn("-mx-1 inline-flex items-center gap-1 rounded px-1 hover:text-foreground", f.sort === sort && "text-foreground")}>
        {label}
        {f.sort === sort ? (f.order === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />) : null}
      </button>
    </TableHead>
  )
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["journeys", filters, page, size],
    queryFn: () => analyticsAPI.listJourneys(filters, size, (page - 1) * size),
    refetchInterval: 60_000, placeholderData: keepPreviousData,
  })

  const exportCsv = async () => {
    setExporting(true)
    try {
      saveBlob(await analyticsAPI.exportJourneysCSV(filters), `crawldoctor_journeys_${range.start}_to_${range.end}_${targetPath || "all"}.csv`)
    } catch (e) {
      toast.error("Export failed", { description: `${apiError(e)}. Try again or use a shorter range.` })
    } finally {
      setExporting(false)
    }
  }

  return (
    <>
      <PageHeader title="Journeys" description={describe("/journeys")}>
        <DateRangePicker value={range} onChange={setRange} />
        <Button size="sm" variant="outline" onClick={exportCsv} disabled={exporting}>
          {exporting ? <Loader2 className="animate-spin" /> : <Download />}Export CSV
        </Button>
      </PageHeader>

      <Page>
        <FilterBar>
          <SearchInput label="Visited a path" placeholder="Visited a path, e.g. /pricing" mono className="max-w-sm"
            value={f.path} onChange={(path) => set({ path })} />
          <FilterSelect label="First-touch source" allLabel="All sources" value={f.source} onChange={(source) => set({ source })}
            options={[...sources.map((v) => ({ value: v.value, label: v.value, count: v.count })), { value: "direct", label: "direct" }]} />
          <FilterSelect label="Campaign" allLabel="All campaigns" value={f.campaign} onChange={(campaign) => set({ campaign })}
            options={[...campaigns.map((v) => ({ value: v.value, label: v.value, count: v.count })), { value: "none", label: "No campaign" }]} />
          <FilterSwitch label="Only people who submitted a form" checked={f.forms === "1"} onChange={(v) => set({ forms: v ? "1" : "0" })} />
          <ClearFilters active={active} onClear={clear} />
          <ResultCount count={data?.total_count} noun="journeys" loading={!data} />
        </FilterBar>

        <Card className="overflow-hidden py-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Visitor</TableHead>
                  <TableHead>First touch</TableHead>
                  <TableHead>Campaign</TableHead>
                  {sortHead("visit_count", "Path")}
                  {sortHead("first_seen", "First seen")}
                  {sortHead("last_seen", "Last seen")}
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && <LoadingRows cols={7} />}
                {(isError || data?.error) && <EmptyRow cols={7} error title="Couldn't load journeys" description={data?.error ?? apiError(error)} />}
                {data && !data.error && data.journeys.length === 0 && (
                  <EmptyRow cols={7} icon={<Route />} title="No journeys found"
                    description={targetPath ? `Nobody visited a path containing "${targetPath}" in this range.` : active ? "Clear a filter or pick a wider date range." : "Try a wider date range or turn off the form filter."} />
                )}
                {data?.journeys.map((j) => {
                  const forms = j.form_fill_count ?? (j.has_captured_data ? 1 : 0)
                  return (
                    <TableRow key={j.client_id} className="cursor-pointer" onClick={() => setDetail({ kind: "journey", id: j.client_id })}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <ShortId id={j.client_id} />
                          {forms > 0 && <Badge variant="outline" className="gap-1 font-normal text-good"><FileCheck2 />{plural(forms, "form")}</Badge>}
                        </div>
                      </TableCell>
                      <TableCell className="max-w-40"><SourceText source={j.source} className="block" /></TableCell>
                      <TableCell className="max-w-48 truncate text-muted-foreground" title={j.campaign}>{j.campaign || "—"}</TableCell>
                      <TableCell className="max-w-96">
                        <div className="flex min-w-0 items-center gap-1.5 font-mono text-xs" title={`${j.entry_page} → ${j.exit_page}`}>
                          <span className="truncate">{stripOrigin(j.entry_page) || "—"}</span>
                          <ArrowRight className="size-3 shrink-0 text-muted-foreground" />
                          <span className="truncate">{stripOrigin(j.exit_page) || "—"}</span>
                        </div>
                        <div className="mt-0.5 text-xs text-muted-foreground tabular-nums">{plural(j.visit_count ?? 0, "page view")}</div>
                      </TableCell>
                      <TableCell className="text-muted-foreground tabular-nums">{shortDate(j.first_seen)}</TableCell>
                      <TableCell className="tabular-nums">{relativeTime(j.last_seen)}</TableCell>
                      <TableCell><ChevronRight className="size-4 text-muted-foreground" /></TableCell>
                    </TableRow>
                  )
                })}
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
