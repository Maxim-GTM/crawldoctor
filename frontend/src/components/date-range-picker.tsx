import { useEffect, useState } from "react"
import { CalendarDays, Check } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Separator } from "@/components/ui/separator"
import type { Range } from "@/lib/api"
import { daysAgo, rangeLabel } from "@/lib/format"
import { cn } from "@/lib/utils"

const PRESETS = [
  { days: 0, label: "Today" },
  { days: 7, label: "Last 7 days" },
  { days: 30, label: "Last 30 days" },
  { days: 90, label: "Last 90 days" },
]

const presetOf = (r: Range) => (r.end === daysAgo(0) ? PRESETS.find((p) => r.start === daysAgo(p.days)) : undefined)

/** A "Last 7 days ▾" button with presets and a custom from/to (UTC days, as the API reads them). */
export function DateRangePicker({ value, onChange, className }: {
  value: Range; onChange: (r: Range) => void; className?: string
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(value)
  useEffect(() => { if (open) setDraft(value) }, [open, value])
  const preset = presetOf(value)
  const valid = !!draft.start && !!draft.end && draft.start <= draft.end

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger render={<Button variant="outline" size="sm" className={cn("tabular-nums", className)} />}>
        <CalendarDays />
        {preset?.label ?? rangeLabel(value.start, value.end)}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 gap-2 p-2">
        <div className="grid gap-0.5">
          {PRESETS.map((p) => {
            const on = preset?.days === p.days
            return (
              <Button key={p.days} variant="ghost" size="sm" className="justify-between font-normal"
                onClick={() => { onChange({ start: daysAgo(p.days), end: daysAgo(0) }); setOpen(false) }}>
                {p.label}
                {on && <Check className="text-muted-foreground" />}
              </Button>
            )
          })}
        </div>
        <Separator />
        <form className="grid gap-2 p-1" onSubmit={(e) => { e.preventDefault(); if (valid) { onChange(draft); setOpen(false) } }}>
          <div className="grid grid-cols-2 gap-2">
            <Field className="gap-1">
              <FieldLabel htmlFor="range-from" className="text-xs text-muted-foreground">From</FieldLabel>
              <Input id="range-from" type="date" className="h-7 px-1.5 text-xs" value={draft.start} max={draft.end}
                onChange={(e) => setDraft((d) => ({ ...d, start: e.target.value }))} />
            </Field>
            <Field className="gap-1">
              <FieldLabel htmlFor="range-to" className="text-xs text-muted-foreground">To</FieldLabel>
              <Input id="range-to" type="date" className="h-7 px-1.5 text-xs" value={draft.end} min={draft.start}
                onChange={(e) => setDraft((d) => ({ ...d, end: e.target.value }))} />
            </Field>
          </div>
          <Button type="submit" size="sm" disabled={!valid}>Apply custom range</Button>
          <p className="text-[11px] text-muted-foreground">Days run midnight to midnight UTC.</p>
        </form>
      </PopoverContent>
    </Popover>
  )
}
