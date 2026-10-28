import { useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { ChevronRight, Download, Inbox, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { ShortId } from "@/components/client-id"
import { DataPagination } from "@/components/data-pagination"
import { DateRangePicker } from "@/components/date-range-picker"
import { DetailSheet, type Detail } from "@/components/detail-sheet"
import { ClearFilters, FilterBar, ResultCount, SearchInput, SuggestInput, useFacet } from "@/components/filters"
import { Page, PageHeader } from "@/components/page-header"
import { EmptyRow, LoadingRows } from "@/components/table-state"
import { SourceText } from "@/components/visitor-badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useDateRange } from "@/hooks/use-date-range"
import { usePage, useUrlFilters } from "@/hooks/use-url-filters"
import { analyticsAPI, apiError, saveBlob } from "@/lib/api"
import { fullTime, num, relativeTime } from "@/lib/format"
import { describe } from "@/lib/nav"

const FILTERS = { q: "", path: "", source: "", medium: "", campaign: "" }
const CHIPS = 5

export function LeadsPage() {
  const [range, setRange] = useDateRange(30)
  const { filters: f, set, clear, active } = useUrlFilters(FILTERS)
  const [page, setPage] = usePage(JSON.stringify([range, f]))
  const [size, setSize] = useState(20)
  const [exporting, setExporting] = useState(false)
  const [detail, setDetail] = useState<Detail | null>(null)
  // The pages that actually captured leads in this range, most first
  const paths = useFacet("leads.captured_path", range)
  const chips = paths.slice(0, CHIPS)
  if (f.path && !chips.some((c) => c.value === f.path)) chips.push({ value: f.path, count: paths.find((p) => p.value === f.path)?.count ?? 0 })

  const filters = {
    q: f.q.trim() || undefined, capturedPath: f.path || undefined,
    source: f.source.trim() || undefined, medium: f.medium.trim() || undefined, campaign: f.campaign.trim() || undefined,
    ...range,
  }
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["leads", filters, page, size],
    queryFn: () => analyticsAPI.listLeads(filters, size, (page - 1) * size),
    refetchInterval: 60_000, placeholderData: keepPreviousData,
  })

  const exportCsv = async () => {
    setExporting(true)
    try {
      saveBlob(await analyticsAPI.exportLeadsCSV(filters), `crawldoctor_leads_${range.start}_to_${range.end}.csv`)
    } catch (e) {
      toast.error("Export failed", { description: `${apiError(e)}. Try again or use a shorter range.` })
    } finally {
      setExporting(false)
    }
  }

  const filtered = active > 0

  return (
    <>
      <PageHeader title="Leads" description={describe("/leads")}>
        <DateRangePicker value={range} onChange={setRange} />
        <Button size="sm" variant="outline" onClick={exportCsv} disabled={exporting}>
          {exporting ? <Loader2 className="animate-spin" /> : <Download />}Export CSV
        </Button>
      </PageHeader>

      <Page>
        <div className="space-y-3">
          <ToggleGroup variant="outline" size="sm" spacing={1} className="flex-wrap" value={[f.path || "all"]}
            onValueChange={(v) => { const p = (v as string[])[0]; if (p) set({ path: p === "all" ? "" : p }) }}>
            <ToggleGroupItem value="all" aria-label="Captured on any page">All pages</ToggleGroupItem>
            {chips.map((c) => (
              <ToggleGroupItem key={c.value} value={c.value} aria-label={`Captured on ${c.value}`} className="gap-1.5 font-mono text-xs">
                {c.value}<span className="font-sans text-muted-foreground tabular-nums">{num(c.count)}</span>
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <FilterBar>
            <SearchInput label="Search leads by name, email or company" placeholder="Name, email or company" className="max-w-64"
              value={f.q} onChange={(q) => set({ q })} />
            {(["source", "medium", "campaign"] as const).map((k) => (
              <SuggestInput key={k} placeholder={`utm_${k}`} label={`Filter by utm_${k} (exact)`} className="w-32"
                value={f[k]} onChange={(v) => set({ [k]: v })} />
            ))}
            <ClearFilters active={active} onClear={clear} />
            <ResultCount count={data?.total_count} noun="leads" loading={!data} />
          </FilterBar>
        </div>

        <Card className="overflow-hidden py-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Lead</TableHead>
                  <TableHead>Captured on</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Captured</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && <LoadingRows cols={5} />}
                {(isError || data?.error) && <EmptyRow cols={5} error title="Couldn't load leads" description={data?.error ?? apiError(error)} />}
                {data && !data.error && data.leads.length === 0 && (
                  <EmptyRow cols={5} icon={<Inbox />} title="No leads found"
                    description={filtered ? "Nothing matches these filters in this range." : "Form submissions on tracked pages show up here."} />
                )}
                {data?.leads.map((l) => (
                  <TableRow key={l.client_id} className="cursor-pointer" onClick={() => setDetail({ kind: "journey", id: l.client_id })}>
                    <TableCell className="max-w-72">
                      {l.name || l.email ? (
                        <>
                          <div className="truncate font-medium">{l.name || l.email}</div>
                          <div className="truncate text-xs text-muted-foreground">
                            {l.name ? (l.email || (l.company ? null : <ShortId id={l.client_id} />)) : <ShortId id={l.client_id} />}
                            {l.company && <>{(l.name ? l.email : true) && " · "}{l.company}</>}
                          </div>
                        </>
                      ) : <ShortId id={l.client_id} />}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{l.captured_path || "—"}</TableCell>
                    <TableCell className="max-w-56"><SourceText source={l.source} medium={l.medium} campaign={l.campaign} className="block" /></TableCell>
                    <TableCell className="tabular-nums" title={fullTime(l.captured_at)}>{relativeTime(l.captured_at)}</TableCell>
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
