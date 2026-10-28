import { useEffect, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { CornerDownLeft, FileText, History, Loader2, Route, Search } from "lucide-react"
import { useNavigate } from "react-router-dom"

import { DetailSheet, type Detail } from "@/components/detail-sheet"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Kbd, KbdGroup } from "@/components/ui/kbd"
import { useDebounced } from "@/hooks/use-debounced"
import { analyticsAPI, apiError, type SearchResult } from "@/lib/api"
import { relativeTime } from "@/lib/format"
import { cn } from "@/lib/utils"

const ICONS = { journey: Route, session: History, page: FileText }
const KIND_LABEL = { journey: "Visitor", session: "Session", page: "Page views" }
const isMac = typeof navigator !== "undefined" && /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent)

/** "last active 2026-10-28T…" from the API reads better as "last active 3 h ago". */
const readable = (detail?: string | null) =>
  detail?.replace(/\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})?/g, (iso) => relativeTime(iso)) ?? ""

/**
 * ⌘K / Ctrl+K from anywhere: paste an email, name, client ID, session ID or page URL and open
 * the visitor, session or page views it points at.
 */
export function CommandSearch() {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState("")
  const [active, setActive] = useState(0)
  const [detail, setDetail] = useState<Detail | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const q = useDebounced(text.trim(), 200)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); setOpen((o) => !o) }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const { data, isFetching, isError, error } = useQuery({
    queryKey: ["search", q], queryFn: () => analyticsAPI.search(q), enabled: open && q.length >= 2, staleTime: 30_000,
  })
  const results = q.length >= 2 ? data?.results ?? [] : []
  useEffect(() => setActive(0), [q])

  const choose = (r: SearchResult) => {
    setOpen(false)
    setText("")
    if (r.kind === "page") {
      const params = new URLSearchParams()
      if (r.path) params.set("path", r.path)
      if (r.domain) params.set("domain", r.domain)
      navigate(`/dashboard?${params}#recent`)
    } else {
      setDetail({ kind: r.kind, id: r.id })
    }
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!results.length) return
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => (i + 1) % results.length) }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => (i - 1 + results.length) % results.length) }
    else if (e.key === "Enter") { e.preventDefault(); choose(results[active]) }
  }

  const waiting = q.length >= 2 && (isFetching || q !== text.trim())

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} aria-label="Search"
        className="w-9 justify-start px-0 text-muted-foreground max-sm:justify-center sm:w-56 sm:px-2.5">
        <Search />
        <span className="hidden flex-1 text-left font-normal sm:inline">Find a visitor or session…</span>
        <KbdGroup className="hidden sm:inline-flex"><Kbd>{isMac ? "⌘" : "Ctrl"}</Kbd><Kbd>K</Kbd></KbdGroup>
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent showCloseButton={false} initialFocus={input} className="top-[18%] translate-y-0 gap-0 overflow-hidden p-0 sm:max-w-xl">
          <DialogTitle className="sr-only">Search</DialogTitle>
          <DialogDescription className="sr-only">Paste an email, client ID, session ID or page URL</DialogDescription>
          <div className="flex items-center gap-2 border-b px-3">
            {waiting ? <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" /> : <Search className="size-4 shrink-0 text-muted-foreground" />}
            <input ref={input} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKeyDown}
              placeholder="Email, name, client ID, session ID or URL" aria-label="Search"
              role="combobox" aria-expanded={results.length > 0} aria-controls="command-results"
              aria-activedescendant={results.length ? `command-result-${active}` : undefined}
              className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground" />
          </div>
          <div id="command-results" role="listbox" className="max-h-80 overflow-y-auto p-1.5">
            {q.length < 2 ? (
              <p className="px-2 py-6 text-center text-sm text-muted-foreground">
                Paste an email, a client or session ID (or its first characters), or a page URL.
              </p>
            ) : isError ? (
              <p className="px-2 py-6 text-center text-sm text-destructive">Search failed: {apiError(error)}</p>
            ) : !results.length ? (
              <p className="px-2 py-6 text-center text-sm text-muted-foreground">{waiting ? "Searching…" : "Nothing matches that."}</p>
            ) : results.map((r, i) => {
              const Icon = ICONS[r.kind]
              return (
                <button key={`${r.kind}:${r.id}`} id={`command-result-${i}`} role="option" aria-selected={i === active} type="button"
                  onMouseMove={() => setActive(i)} onClick={() => choose(r)}
                  className={cn("flex w-full items-center gap-3 rounded-md px-2 py-2 text-left", i === active && "bg-accent text-accent-foreground")}>
                  <Icon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{r.label}</span>
                    {r.detail && <span className="block truncate text-xs text-muted-foreground">{readable(r.detail)}</span>}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">{KIND_LABEL[r.kind]}</span>
                  {i === active && <CornerDownLeft className="size-3.5 shrink-0 text-muted-foreground" />}
                </button>
              )
            })}
          </div>
        </DialogContent>
      </Dialog>

      <DetailSheet detail={detail} onChange={setDetail} />
    </>
  )
}
