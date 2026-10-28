import { useEffect, useMemo, useState } from "react"
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight, ChevronRight, Filter, Loader2, Plus, Settings2, Timer, Trash2, Users, X } from "lucide-react"
import { toast } from "sonner"

import { ShortId } from "@/components/client-id"
import { DateRangePicker } from "@/components/date-range-picker"
import { DetailSheet, type Detail } from "@/components/detail-sheet"
import { FunnelSteps, funnelRate } from "@/components/funnel-steps"
import { Page, PageHeader } from "@/components/page-header"
import { SourceText } from "@/components/visitor-badge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useDateRange } from "@/hooks/use-date-range"
import { analyticsAPI, apiError, type FunnelDef, type FunnelPerson, type FunnelStep, type Range } from "@/lib/api"
import { plural, relativeTime, seconds, stripOrigin } from "@/lib/format"
import { describe } from "@/lib/nav"
import { cn } from "@/lib/utils"

export function FunnelsPage() {
  const [range, setRange] = useDateRange(30)
  const [configOpen, setConfigOpen] = useState(false)
  const [selected, setSelected] = useState("")
  const [detail, setDetail] = useState<Detail | null>(null)

  const { data, isLoading } = useQuery({ queryKey: ["funnel-summary", range], queryFn: () => analyticsAPI.getFunnelSummary(range), refetchInterval: 60_000, placeholderData: keepPreviousData })
  const funnels = useMemo(() => (data?.funnels ?? []).map((f) => ({ ...f, key: f.key || f.label })), [data])
  useEffect(() => {
    if (funnels.length && !funnels.some((f) => f.key === selected)) setSelected(funnels[0].key)
  }, [funnels, selected])
  const current = funnels.find((f) => f.key === selected)

  return (
    <>
      <PageHeader title="Funnels" description={describe("/funnels")}>
        <DateRangePicker value={range} onChange={setRange} />
        <Button size="sm" variant="outline" onClick={() => setConfigOpen(true)}><Settings2 />Configure funnels</Button>
      </PageHeader>

      <Page>
        {isLoading ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-56" />)}</div>
        ) : funnels.length === 0 ? (
          <Empty className="border">
            <EmptyHeader>
              <EmptyMedia variant="icon"><Filter /></EmptyMedia>
              <EmptyTitle>No funnels yet</EmptyTitle>
              <EmptyDescription>A funnel is a list of pages and events people go through in order, like /demo → form submit → /schedule.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent><Button onClick={() => setConfigOpen(true)}><Plus />Add a funnel</Button></EmptyContent>
          </Empty>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {funnels.map((f) => {
              const on = f.key === selected
              return (
                <Card key={f.key} role="button" tabIndex={0} aria-pressed={on}
                  className={cn("cursor-pointer transition-shadow hover:ring-foreground/20", on && "ring-2 ring-primary/70 hover:ring-primary/70")}
                  onClick={() => setSelected(f.key)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelected(f.key) } }}>
                  <CardHeader>
                    <CardTitle className="leading-snug">{f.label}</CardTitle>
                    <CardDescription>{plural(f.stages[0]?.count ?? 0, "person", "people")} started</CardDescription>
                    <CardAction className="text-right">
                      <div className="text-2xl font-semibold tabular-nums">{funnelRate(f).toFixed(1)}%</div>
                      <div className="text-xs text-muted-foreground">converted</div>
                    </CardAction>
                  </CardHeader>
                  <CardContent><FunnelSteps funnel={f} /></CardContent>
                </Card>
              )
            })}
          </div>
        )}

        {current && (
          <section className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">Funnel detail</h2>
              <Select items={Object.fromEntries(funnels.map((f) => [f.key, f.label]))} value={selected} onValueChange={(v) => setSelected(String(v))}>
                <SelectTrigger size="sm" className="max-w-full sm:max-w-sm" aria-label="Funnel"><SelectValue /></SelectTrigger>
                <SelectContent>{funnels.map((f) => <SelectItem key={f.key} value={f.key}>{f.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="grid gap-4 lg:grid-cols-5 lg:items-start">
              <TimingCard funnelKey={current.key} range={range} className="lg:col-span-2" />
              <PeopleCard key={current.key} funnelKey={current.key} stages={current.stages.map((s) => s.label)} range={range}
                onOpen={(id) => setDetail({ kind: "journey", id })} className="lg:col-span-3" />
            </div>
          </section>
        )}
      </Page>

      <FunnelConfigDialog open={configOpen} onOpenChange={setConfigOpen} />
      <DetailSheet detail={detail} onChange={setDetail} />
    </>
  )
}

function TimingCard({ funnelKey, range, className }: { funnelKey: string; range: Range; className?: string }) {
  const { data, isLoading } = useQuery({ queryKey: ["funnel-timing", funnelKey, range], queryFn: () => analyticsAPI.getFunnelTiming(funnelKey, range) })
  const transitions = data?.transitions ?? []
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Timer className="size-4 text-muted-foreground" />Time to convert</CardTitle>
        <CardDescription>How long people took between steps</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? <Skeleton className="h-24" /> : transitions.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Nobody has moved between steps in this range.</p>
        ) : transitions.map((t) => (
          <div key={`${t.from}-${t.to}`} className="space-y-2.5 rounded-lg border p-3">
            <div className="flex items-start justify-between gap-2 text-sm">
              <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                <span className="truncate">{t.from}</span><ArrowRight className="size-3 shrink-0 text-muted-foreground" /><span className="truncate">{t.to}</span>
              </span>
              <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{plural(t.sample_size, "person", "people")}</span>
            </div>
            <dl className="grid grid-cols-3 gap-2">
              {([["Median", t.median_seconds], ["Average", t.avg_seconds], ["90th pct.", t.p90_seconds]] as const).map(([l, v]) => (
                <div key={l}>
                  <dt className="text-xs text-muted-foreground">{l}</dt>
                  <dd className="font-semibold tabular-nums">{seconds(v)}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function PeopleCard({ funnelKey, stages, range, onOpen, className }: {
  funnelKey: string; stages: string[]; range: Range; onOpen: (clientId: string) => void; className?: string
}) {
  const [view, setView] = useState<"reached" | "dropoff">("reached")
  const [step, setStep] = useState(0)
  const [capturedOnly, setCapturedOnly] = useState(false)
  // Drop-offs are between steps, so there is one fewer choice than stages
  const options = view === "reached" ? stages.map((s, i) => [String(i), s]) : stages.slice(0, -1).map((s, i) => [String(i), `After “${s}”`])
  const safeStep = Math.min(step, Math.max(0, options.length - 1))

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["funnel-people", funnelKey, view, safeStep, range],
    queryFn: () => view === "reached"
      ? analyticsAPI.getFunnelStageUsers(funnelKey, safeStep, range)
      : analyticsAPI.getFunnelDropoffs(funnelKey, safeStep, range),
    enabled: options.length > 0,
  })
  const people = (data?.users ?? []).filter((u) => view !== "reached" || !capturedOnly || u.has_captured_data)

  return (
    <Card className={cn("gap-0 overflow-hidden pb-0", className)}>
      <CardHeader className="gap-3 border-b pb-4">
        <CardTitle className="flex items-center gap-2"><Users className="size-4 text-muted-foreground" />People</CardTitle>
        <CardDescription>Who reached a step, or who stopped after it (up to 50)</CardDescription>
        <div className="col-span-full flex flex-wrap items-center gap-2">
          <ToggleGroup variant="outline" size="sm" value={[view]} onValueChange={(v) => { const n = (v as string[])[0]; if (n) setView(n as typeof view) }}>
            <ToggleGroupItem value="reached">Reached</ToggleGroupItem>
            <ToggleGroupItem value="dropoff">Dropped off</ToggleGroupItem>
          </ToggleGroup>
          {options.length > 0 && (
            <Select items={Object.fromEntries(options)} value={String(safeStep)} onValueChange={(v) => setStep(Number(v))}>
              <SelectTrigger size="sm" className="max-w-64" aria-label="Step"><SelectValue /></SelectTrigger>
              <SelectContent>{options.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
            </Select>
          )}
          {view === "reached" && (
            <div className="flex items-center gap-2">
              <Switch id="captured-only" size="sm" checked={capturedOnly} onCheckedChange={setCapturedOnly} />
              <Label htmlFor="captured-only" className="text-xs font-normal">With captured data</Label>
            </div>
          )}
        </div>
      </CardHeader>
      <div className="max-h-[28rem] divide-y overflow-y-auto">
        {options.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">A one-step funnel has no drop-offs.</p>
        ) : isLoading ? (
          <div className="space-y-2 p-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
        ) : isError ? (
          <p className="p-6 text-center text-sm text-destructive">{apiError(error)}</p>
        ) : people.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">{view === "reached" ? "Nobody reached this step." : "No drop-offs after this step."}</p>
        ) : people.map((u) => <PersonRow key={u.client_id} person={u} onOpen={() => onOpen(u.client_id)} />)}
      </div>
    </Card>
  )
}

function capturedSummary(data: unknown): string {
  let v = data
  if (typeof v === "string") { try { v = JSON.parse(v) } catch { return v as string } }
  if (v && typeof v === "object") return Object.entries(v).slice(0, 3).map(([k, x]) => `${k}: ${x}`).join(" · ")
  return ""
}

function PersonRow({ person: u, onOpen }: { person: FunnelPerson; onOpen: () => void }) {
  const captured = u.has_captured_data ? capturedSummary(u.captured_data) : ""
  return (
    <button type="button" onClick={onOpen} className="grid w-full grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-0.5 px-4 py-2.5 text-left text-sm hover:bg-muted/50">
      <div className="flex min-w-0 items-center gap-2">
        {u.name || u.email ? <span className="truncate font-medium">{u.name || u.email}</span> : <ShortId id={u.client_id} />}
        {u.has_captured_data && <Badge variant="outline" className="font-normal text-good">Captured</Badge>}
      </div>
      <span className="flex items-center gap-1 text-xs text-muted-foreground tabular-nums">
        {relativeTime(u.stage_reached_at || u.last_seen)}<ChevronRight className="size-4" />
      </span>
      <div className="col-span-2 flex min-w-0 flex-wrap gap-x-3 text-xs text-muted-foreground">
        <SourceText source={u.source} medium={u.medium} campaign={u.campaign} />
        {u.entry_page && <span className="truncate font-mono">entered {stripOrigin(u.entry_page)}</span>}
        {captured && <span className="truncate">{captured}</span>}
      </div>
    </button>
  )
}

/* ---------- Configuration ---------- */

const newStep = (): FunnelStep => ({ label: "Submitted form", type: "event", path: "/", event_type: "form_submit" })

function FunnelConfigDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ["funnel-config"], queryFn: analyticsAPI.getFunnelConfig, enabled: open })
  const [draft, setDraft] = useState<FunnelDef[]>([])
  useEffect(() => { if (open && data?.funnels) setDraft(data.funnels) }, [open, data])

  const save = useMutation({
    mutationFn: () => analyticsAPI.saveFunnelConfig({ funnels: draft }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["funnel-summary"] })
      queryClient.invalidateQueries({ queryKey: ["funnel-config"] })
      onOpenChange(false)
      toast.success("Funnels saved")
    },
    onError: (e) => toast.error("Couldn't save the funnels", { description: apiError(e) }),
  })

  const setFunnel = (i: number, u: Partial<FunnelDef>) => setDraft((d) => d.map((f, j) => (j === i ? { ...f, ...u } : f)))
  const setStep = (i: number, s: number, u: Partial<FunnelStep>) =>
    setDraft((d) => d.map((f, j) => (j === i ? { ...f, steps: f.steps.map((st, k) => (k === s ? { ...st, ...u } : st)) } : f)))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-0 p-0 sm:max-w-3xl">
        <DialogHeader className="border-b p-4">
          <DialogTitle>Configure funnels</DialogTitle>
          <DialogDescription>Each step matches a page path (prefix) or an event on that path. People must hit the steps in order.</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          {isLoading ? <Skeleton className="h-48" /> : draft.map((f, i) => (
            <fieldset key={i} className="space-y-3 rounded-lg border p-3">
              <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] sm:items-end">
                <Field className="gap-1.5">
                  <FieldLabel htmlFor={`f${i}-label`}>Funnel name</FieldLabel>
                  <Input id={`f${i}-label`} value={f.label} onChange={(e) => setFunnel(i, { label: e.target.value })} />
                </Field>
                <Field className="gap-1.5">
                  <FieldLabel htmlFor={`f${i}-key`}>Key</FieldLabel>
                  <Input id={`f${i}-key`} className="font-mono text-[13px]" value={f.key} onChange={(e) => setFunnel(i, { key: e.target.value })} />
                </Field>
                <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => setDraft((d) => d.filter((_, j) => j !== i))}>
                  <Trash2 />Remove funnel
                </Button>
              </div>

              <ol className="space-y-2">
                {f.steps.map((st, s) => (
                  <li key={s} className="grid grid-cols-[1.5rem_minmax(0,1fr)_auto] items-start gap-2 rounded-md bg-muted/50 p-2">
                    <span className="mt-1.5 flex size-5 items-center justify-center rounded-full bg-background text-[11px] font-medium tabular-nums ring-1 ring-border">{s + 1}</span>
                    <div className="grid gap-2 sm:grid-cols-[minmax(0,1.4fr)_7.5rem_minmax(0,1fr)_minmax(0,1fr)]">
                      <Input aria-label={`Step ${s + 1} label`} placeholder="Label" value={st.label} onChange={(e) => setStep(i, s, { label: e.target.value })} />
                      <Select items={{ page: "Page visit", event: "Event" }} value={st.type} onValueChange={(v) => setStep(i, s, { type: v as FunnelStep["type"] })}>
                        <SelectTrigger aria-label={`Step ${s + 1} type`} className="w-full"><SelectValue /></SelectTrigger>
                        <SelectContent><SelectItem value="page">Page visit</SelectItem><SelectItem value="event">Event</SelectItem></SelectContent>
                      </Select>
                      <Input aria-label={`Step ${s + 1} path`} placeholder="/path" className="font-mono text-[13px]" value={st.path} onChange={(e) => setStep(i, s, { path: e.target.value })} />
                      <Input aria-label={`Step ${s + 1} event type`} placeholder={st.type === "event" ? "form_submit" : "—"} className="font-mono text-[13px]"
                        disabled={st.type !== "event"} value={st.event_type ?? ""} onChange={(e) => setStep(i, s, { event_type: e.target.value })} />
                    </div>
                    <Button variant="ghost" size="icon-sm" aria-label={`Remove step ${s + 1}`} className="text-muted-foreground"
                      onClick={() => setFunnel(i, { steps: f.steps.filter((_, k) => k !== s) })}><X /></Button>
                  </li>
                ))}
              </ol>
              <Button variant="outline" size="sm" onClick={() => setFunnel(i, { steps: [...f.steps, newStep()] })}><Plus />Add step</Button>
            </fieldset>
          ))}
          {!isLoading && (
            <Button variant="outline" className="w-full border-dashed"
              onClick={() => setDraft((d) => [...d, { key: `custom_${Date.now()}`, label: "New funnel", steps: [{ label: "Visited /path", type: "page", path: "/" }] }])}>
              <Plus />Add funnel
            </Button>
          )}
        </div>
        <DialogFooter className="m-0 rounded-b-xl border-t p-4">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || isLoading}>
            {save.isPending && <Loader2 className="animate-spin" />}Save funnels
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
