import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { ArrowUpRight, FileText } from "lucide-react"
import { Link } from "react-router-dom"

import { DateRangePicker } from "@/components/date-range-picker"
import { ClearFilters, FilterBar, FilterSelect, FilterSwitch, ResultCount, SearchInput, useFacet } from "@/components/filters"
import { Page, PageHeader } from "@/components/page-header"
import { EmptyRow, LoadingRows } from "@/components/table-state"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useDateRange } from "@/hooks/use-date-range"
import { useUrlFilters } from "@/hooks/use-url-filters"
import { analyticsAPI, apiError } from "@/lib/api"
import { fullTime, num, pct, relativeTime } from "@/lib/format"
import { describe } from "@/lib/nav"

const FILTERS = { path: "", domain: "", bots: "" }

/** The most viewed pages by path (the Overview's sites card only splits by domain). */
export function PagesPage() {
  const [range, setRange] = useDateRange(30)
  const { filters: f, set, clear, active } = useUrlFilters(FILTERS)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["top-pages", range, f],
    queryFn: () => analyticsAPI.getTopPages(range, { humansOnly: !f.bots, domain: f.domain || undefined, path: f.path.trim() || undefined, limit: 100 }),
    placeholderData: keepPreviousData,
  })
  const domains = useFacet("visits.page_domain", range, !f.bots)
  const pages = data?.pages ?? []
  const max = Math.max(1, ...pages.map((p) => p.views))
  const total = pages.reduce((a, p) => a + p.views, 0)

  return (
    <>
      <PageHeader title="Pages" description={describe("/pages")}>
        <DateRangePicker value={range} onChange={setRange} />
      </PageHeader>
      <Page>
        <FilterBar>
          <SearchInput label="Path contains" placeholder="Path contains, e.g. /articles" mono className="max-w-72" value={f.path} onChange={(path) => set({ path })} />
          <FilterSelect label="Site" allLabel="All sites" value={f.domain} onChange={(domain) => set({ domain })}
            options={domains.map((d) => ({ value: d.value, label: d.value, count: d.count }))} />
          <FilterSwitch label="Include bots and crawlers" checked={!!f.bots} onChange={(v) => set({ bots: v ? "1" : "" })} />
          <ClearFilters active={active} onClear={clear} />
          <ResultCount count={data ? pages.length : undefined} noun={pages.length === 100 ? "pages (top 100)" : "pages"} />
        </FilterBar>

        <Card className="overflow-hidden py-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Page</TableHead>
                  <TableHead className="w-[28%] text-right">Page views</TableHead>
                  <TableHead className="text-right">Unique visitors</TableHead>
                  <TableHead>Last view</TableHead>
                  <TableHead className="w-10"><span className="sr-only">Views</span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && <LoadingRows cols={5} />}
                {isError && <EmptyRow cols={5} error title="Couldn't load pages" description={apiError(error)} />}
                {data && pages.length === 0 && (
                  <EmptyRow cols={5} icon={<FileText />} title="No page views match" description="Clear a filter or pick a wider date range." />
                )}
                {pages.map((p) => (
                  <TableRow key={`${p.domain}${p.path}`}>
                    <TableCell className="max-w-[28rem]">
                      <a href={`https://${p.domain}${p.path}`} target="_blank" rel="noopener noreferrer" className="block truncate font-mono text-xs hover:underline" title={`${p.domain}${p.path}`}>
                        {p.path}
                      </a>
                      <div className="truncate text-xs text-muted-foreground">{p.domain}</div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-3">
                        <div className="hidden h-1.5 flex-1 overflow-hidden rounded-full bg-muted sm:block">
                          <div className="h-full rounded-full bg-[var(--series-1)]" style={{ width: `${(p.views / max) * 100}%` }} />
                        </div>
                        <span className="w-14 text-right font-medium tabular-nums">{num(p.views)}</span>
                        <span className="w-10 text-right text-xs text-muted-foreground tabular-nums">{pct(p.views, total)}</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{num(p.visitors)}</TableCell>
                    <TableCell className="text-muted-foreground tabular-nums" title={fullTime(p.last_seen)}>{relativeTime(p.last_seen)}</TableCell>
                    <TableCell>
                      <Button variant="ghost" size="icon-xs" aria-label="See each view of this page" title="See each view of this page" nativeButton={false}
                        render={<Link to={`/dashboard?${new URLSearchParams({ from: range.start, to: range.end, path: p.path, domain: p.domain, ...(f.bots ? {} : { visitor: "human" }) })}#recent`} />}>
                        <ArrowUpRight />
                      </Button>
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
