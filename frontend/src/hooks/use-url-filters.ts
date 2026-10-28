import { useCallback, useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"

/**
 * A page's filters, kept in the address next to the date range (?from=…&to=…) so a filtered
 * view survives a refresh and can be shared. Each key reads as its default when absent, and
 * setting it back to the default takes it out of the address. Pass `defaults` as a module
 * constant so its identity is stable.
 */
export function useUrlFilters<T extends Record<string, string>>(defaults: T) {
  const [params, setParams] = useSearchParams()
  // Only this page's keys matter: other params (the range, another card's filters) don't re-derive it
  const signature = Object.keys(defaults).map((k) => params.get(k) ?? "\u0000").join("\u0001")
  const filters = useMemo(() => {
    const values = signature.split("\u0001")
    return Object.fromEntries(Object.keys(defaults).map((k, i) => [k, values[i] === "\u0000" ? defaults[k] : values[i]])) as T
  }, [signature, defaults])

  const set = useCallback((patch: Partial<T>) => {
    setParams((p) => {
      const n = new URLSearchParams(p)
      for (const [k, v] of Object.entries(patch)) {
        if (v === undefined || v === defaults[k]) n.delete(k)
        else n.set(k, v as string)
      }
      return n
    }, { replace: true })
  }, [setParams, defaults])

  const clear = useCallback(() => set(defaults), [set, defaults])
  const active = Object.keys(defaults).filter((k) => filters[k] !== defaults[k]).length
  return { filters, set, clear, active }
}

/** Page number that starts again at 1 whenever `resetKey` (e.g. the serialised filters) changes. */
export function usePage(resetKey: string): [number, (p: number) => void] {
  const [state, setState] = useState({ key: resetKey, page: 1 })
  const page = state.key === resetKey ? state.page : 1
  const setPage = useCallback((p: number) => setState({ key: resetKey, page: p }), [resetKey])
  return [page, setPage]
}
