import { ChevronLeft, ChevronRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { Paged } from "@/lib/api"
import { num } from "@/lib/format"

const SIZES = [10, 20, 50, 100]

/**
 * Table footer: "41–60 of 1,284 · Rows 20 ▾ · ‹ Page 3 of 65 ›". Some list endpoints only count
 * exactly on the first page, so the total reads "about" after that.
 */
export function DataPagination({ data, page, pageSize, onPage, onPageSize, approximate }: {
  data: Paged | undefined; page: number; pageSize: number
  onPage: (p: number) => void; onPageSize: (n: number) => void
  /** The API estimates totals past page 1 */
  approximate?: boolean
}) {
  const total = data?.total_count ?? 0
  const pages = Math.max(1, data?.total_pages ?? 1)
  const from = total ? (page - 1) * pageSize + 1 : 0
  const to = Math.min(total, page * pageSize)
  const about = approximate && page > 1

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t px-3 py-2 text-xs text-muted-foreground">
      <span className="tabular-nums">
        {total ? <>{num(from)}–{num(to)} of {about ? "about " : ""}{num(total)}</> : "No rows"}
      </span>
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          <span className="hidden sm:inline">Rows</span>
          <Select items={Object.fromEntries(SIZES.map((s) => [String(s), String(s)]))} value={String(pageSize)}
            onValueChange={(v) => { onPageSize(Number(v)); onPage(1) }}>
            <SelectTrigger size="sm" className="h-7 min-w-16 text-xs" aria-label="Rows per page"><SelectValue /></SelectTrigger>
            <SelectContent>{SIZES.map((s) => <SelectItem key={s} value={String(s)}>{s}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon-xs" disabled={page <= 1} onClick={() => onPage(Math.max(1, page - 1))} aria-label="Previous page">
            <ChevronLeft />
          </Button>
          <span className="tabular-nums">Page {num(page)}{about ? "" : ` of ${num(pages)}`}</span>
          <Button variant="ghost" size="icon-xs" disabled={!data?.has_next} onClick={() => onPage(page + 1)} aria-label="Next page">
            <ChevronRight />
          </Button>
        </div>
      </div>
    </div>
  )
}
