import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { Search, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { analyticsAPI, type FacetField, type Range } from "@/lib/api"
import { num } from "@/lib/format"
import { cn } from "@/lib/utils"

/** The row of filters above a table. */
export function FilterBar({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("flex flex-wrap items-center gap-2", className)}>{children}</div>
}

/**
 * Text that is pushed to `onChange` once typing pauses. It keeps its own state so the caret
 * never jumps while the address updates, and follows `value` when it changes from outside
 * (e.g. "Clear filters").
 */
function useTyped(value: string, onChange: (v: string) => void, ms: number) {
  const [text, setText] = useState(value)
  const sent = useRef(value)
  useEffect(() => {
    if (value !== sent.current) { sent.current = value; setText(value) }
  }, [value])
  useEffect(() => {
    if (text === sent.current) return
    const t = setTimeout(() => { sent.current = text; onChange(text) }, ms)
    return () => clearTimeout(t)
  }, [text, ms, onChange])
  return [text, setText] as const
}

export function SearchInput({ value, onChange, placeholder, label, className, mono, debounce = 350 }: {
  value: string; onChange: (v: string) => void; placeholder: string; label?: string; className?: string; mono?: boolean; debounce?: number
}) {
  const [text, setText] = useTyped(value, onChange, debounce)
  return (
    <div className={cn("relative w-full max-w-xs", className)}>
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input aria-label={label ?? placeholder} placeholder={placeholder} value={text} onChange={(e) => setText(e.target.value)}
        className={cn("h-8 pr-8 pl-8", mono && "font-mono text-[13px] placeholder:font-sans")}
        onKeyDown={(e) => { if (e.key === "Escape" && text) { e.stopPropagation(); setText("") } }} />
      {text && (
        <Button variant="ghost" size="icon-xs" className="absolute top-1/2 right-1.5 -translate-y-1/2" aria-label="Clear"
          onClick={() => setText("")}><X /></Button>
      )}
    </div>
  )
}

/** A free-text filter with the range's common values offered as suggestions (the field still takes anything). */
export function SuggestInput({ value, onChange, suggestions, placeholder, label, className }: {
  value: string; onChange: (v: string) => void; suggestions?: string[]; placeholder: string; label?: string; className?: string
}) {
  const id = useId()
  const [text, setText] = useTyped(value, onChange, 350)
  return (
    <div className={cn("relative w-40", className)}>
      <Input list={`${id}-list`} aria-label={label ?? placeholder} placeholder={placeholder} value={text}
        onChange={(e) => setText(e.target.value)} className={cn("h-8", text && "pr-7")} />
      {text && (
        <Button variant="ghost" size="icon-xs" className="absolute top-1/2 right-1 -translate-y-1/2" aria-label="Clear"
          onClick={() => setText("")}><X /></Button>
      )}
      <datalist id={`${id}-list`}>{suggestions?.map((s) => <option key={s} value={s} />)}</datalist>
    </div>
  )
}

export type Option = { value: string; label: ReactNode; count?: number }

const ALL = "__all__"

/**
 * A select whose first entry ("All countries", say) clears it; `value` is "" for that entry. It is
 * tinted while it narrows the list, i.e. while it holds anything but `defaultValue`.
 */
export function FilterSelect({ value, onChange, options, allLabel, label, className, defaultValue = "" }: {
  value: string; onChange: (v: string) => void; options: Option[]; allLabel: string; label: string; className?: string; defaultValue?: string
}) {
  // Keep a value that came from the address selectable even if this range has no rows for it
  const list = value && !options.some((o) => o.value === value) ? [{ value, label: value }, ...options] : options
  const items = Object.fromEntries([[ALL, allLabel], ...list.map((o) => [o.value, o.label])])
  return (
    <Select items={items} value={value || ALL} onValueChange={(v) => onChange(v === ALL || v == null ? "" : String(v))}>
      <SelectTrigger size="sm" aria-label={label} className={cn("h-8 max-w-56", value !== defaultValue && "border-primary/40 bg-primary/5", className)}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent alignItemWithTrigger={false} align="start" className="max-h-80 w-auto min-w-(--anchor-width) max-w-80">
        <SelectItem value={ALL}>{allLabel}</SelectItem>
        {list.length > 0 && <SelectSeparator />}
        {list.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            <span className="truncate">{o.label}</span>
            {o.count !== undefined && <span className="ml-auto pl-3 text-xs text-muted-foreground tabular-nums">{num(o.count)}</span>}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function FilterSwitch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  const id = useId()
  return (
    <div className="flex h-8 items-center gap-2 px-1">
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
      <Label htmlFor={id} className="font-normal whitespace-nowrap">{label}</Label>
    </div>
  )
}

export function ClearFilters({ active, onClear }: { active: number; onClear: () => void }) {
  if (!active) return null
  return <Button variant="ghost" size="sm" onClick={onClear}><X />Clear {active > 1 ? `${active} filters` : "filter"}</Button>
}

export function ResultCount({ count, noun, loading }: { count?: number; noun: string; loading?: boolean }) {
  return (
    <span className="ml-auto text-xs text-muted-foreground tabular-nums">
      {loading || count === undefined ? "Loading…" : `${num(count)} ${noun}`}
    </span>
  )
}

/* ---------- Option lists ---------- */

const regionNames = typeof Intl !== "undefined" && "DisplayNames" in Intl ? new Intl.DisplayNames(undefined, { type: "region" }) : null

/** "US" → "United States" (falls back to the code). */
export function countryName(code: string): string {
  try {
    return regionNames?.of(code.toUpperCase()) ?? code
  } catch {
    return code
  }
}

/** The range's most common values of one column, for a filter's options or suggestions. */
export function useFacet(field: FacetField, range: Range, humansOnly = false) {
  const { data } = useQuery({
    queryKey: ["facet", field, range, humansOnly],
    queryFn: () => analyticsAPI.getFacet(field, range, humansOnly),
    staleTime: 5 * 60_000,
  })
  return data?.values ?? []
}

export const VISITOR_OPTIONS: Option[] = [
  { value: "human", label: "Humans" },
  { value: "bot", label: "Bots & crawlers" },
]
