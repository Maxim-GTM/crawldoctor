import { Fragment } from "react"

import { cn } from "@/lib/utils"

/** Field names like "what_are_you_hoping_to_solve" may break after each underscore rather than mid-word. */
function Key({ name }: { name: string }) {
  const parts = name.split("_")
  return <>{parts.map((p, i) => <Fragment key={i}>{p}{i < parts.length - 1 && <>_<wbr /></>}</Fragment>)}</>
}

function parse(value: unknown): unknown {
  if (typeof value !== "string") return value
  const s = value.trim()
  if (s.startsWith("{") || s.startsWith("[")) {
    try { return JSON.parse(s) } catch { /* not JSON after all */ }
  }
  return value
}

export function JsonBlock({ value, className }: { value: unknown; className?: string }) {
  return (
    <pre className={cn("max-h-96 overflow-auto rounded-md bg-muted/60 p-2.5 font-mono text-[11px] leading-relaxed whitespace-pre-wrap wrap-anywhere", className)}>
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

/**
 * Captured form values, URL params and the like. Flat objects become a key/value list; nested
 * data falls back to JSON; "a: 1 | b: 2" strings are split into rows.
 */
export function DataValue({ value, className }: { value: unknown; className?: string }) {
  const v = parse(value)
  if (v === null || v === undefined || v === "") return <span className="text-sm text-muted-foreground">—</span>

  if (typeof v === "object" && !Array.isArray(v)) {
    const entries = Object.entries(v as Record<string, unknown>)
    if (!entries.length) return <span className="text-sm text-muted-foreground">Empty</span>
    if (entries.every(([, x]) => x === null || typeof x !== "object")) {
      return (
        <dl className={cn("grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-x-4 text-sm", className)}>
          {entries.map(([k, x]) => (
            <div key={k} className="col-span-2 grid grid-cols-subgrid border-b py-1.5 last:border-0">
              <dt className="text-muted-foreground wrap-anywhere"><Key name={k} /></dt>
              <dd className="wrap-anywhere whitespace-pre-wrap">{x === null || x === "" ? <span className="text-muted-foreground">—</span> : String(x)}</dd>
            </div>
          ))}
        </dl>
      )
    }
  }
  if (typeof v === "object") return <JsonBlock value={v} className={className} />

  const str = String(v)
  if (str.includes("|") && str.includes(":")) {
    return (
      <div className={cn("text-sm", className)}>
        {str.split("|").map((p, i) => <div key={i} className="border-b py-1.5 wrap-anywhere last:border-0">{p.trim()}</div>)}
      </div>
    )
  }
  return <span className={cn("text-sm wrap-anywhere whitespace-pre-wrap", className)}>{str}</span>
}
