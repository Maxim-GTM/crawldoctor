import { useEffect, useState } from "react"

/** The value, once it has stopped changing for `ms` (so typing in a filter doesn't fire a query per key). */
export function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}
