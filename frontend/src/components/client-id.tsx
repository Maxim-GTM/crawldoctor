import { useState } from "react"
import { Check, Copy } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

/** A shortened ID in mono; the tooltip has the whole thing. */
export function ShortId({ id, length = 8, className }: { id?: string | null; length?: number; className?: string }) {
  if (!id) return <span className="text-muted-foreground">—</span>
  return (
    <Tooltip>
      <TooltipTrigger render={<span className={cn("font-mono text-xs tabular-nums", className)} />}>
        {id.length > length ? `${id.slice(0, length)}…` : id}
      </TooltipTrigger>
      <TooltipContent className="font-mono">{id}</TooltipContent>
    </Tooltip>
  )
}

export function CopyButton({ value, label = "Copy", className }: { value: string; label?: string; className?: string }) {
  const [done, setDone] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setDone(true)
      setTimeout(() => setDone(false), 1500)
    } catch { /* clipboard blocked (e.g. inside a frame without permission) */ }
  }
  return (
    <Button variant="ghost" size="icon-xs" className={className} onClick={copy} aria-label={done ? "Copied" : label}>
      {done ? <Check /> : <Copy />}
    </Button>
  )
}
