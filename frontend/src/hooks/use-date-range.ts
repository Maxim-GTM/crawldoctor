import { useCallback, useMemo } from "react"
import { useSearchParams } from "react-router-dom"

import type { Range } from "@/lib/api"
import { daysAgo } from "@/lib/format"

const DAY = /^\d{4}-\d{2}-\d{2}$/

/**
 * The page's date range, kept in the address (?from=…&to=…) so it survives a refresh and can be
 * shared. Without one the page shows the last `defaultDays` days.
 */
export function useDateRange(defaultDays: number): [Range, (r: Range) => void] {
  const [params, setParams] = useSearchParams()
  const from = params.get("from")
  const to = params.get("to")
  const range = useMemo<Range>(() => {
    const end = to && DAY.test(to) ? to : daysAgo(0)
    const start = from && DAY.test(from) ? from : daysAgo(defaultDays)
    return start <= end ? { start, end } : { start: end, end: start }
  }, [from, to, defaultDays])

  const setRange = useCallback((r: Range) => {
    setParams((p) => {
      const n = new URLSearchParams(p)
      n.set("from", r.start)
      n.set("to", r.end)
      return n
    }, { replace: true })
  }, [setParams])

  return [range, setRange]
}
