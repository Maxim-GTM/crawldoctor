import { Badge } from "@/components/ui/badge"
import { KIND_META, visitorKind, type VisitorKind } from "@/lib/visitors"
import { cn } from "@/lib/utils"

export function KindDot({ kind, className }: { kind: VisitorKind; className?: string }) {
  return <span aria-hidden className={cn("inline-block size-2 shrink-0 rounded-full", className)} style={{ background: KIND_META[kind].color }} />
}

/** "● GPTBot", "● Human": the dot says which kind, the text names the crawler. */
export function VisitorBadge({ label, isBot, className }: { label?: string | null; isBot?: boolean | null; className?: string }) {
  const kind = visitorKind(label, isBot)
  const text = label && !/^unknown$/i.test(label) ? label : KIND_META[kind].label
  return (
    <Badge variant="outline" className={cn("gap-1.5 font-normal", className)} title={KIND_META[kind].label}>
      <KindDot kind={kind} />{text}
    </Badge>
  )
}

/**
 * Session lists only know whether a session was mostly bot traffic (the API calls every such
 * session "AI Crawler"), so these read Human / Bot / Unknown rather than guessing which bot.
 */
export function SessionKind({ classification }: { classification?: string | null }) {
  if (classification === "Human") return <VisitorBadge label="Human" isBot={false} />
  if (classification === "AI Crawler") return <VisitorBadge label="Bot" isBot />
  return <Badge variant="outline" className="font-normal text-muted-foreground">Unknown</Badge>
}

/** "google / cpc / launch" with the empty parts left out; "direct" when there are none. */
export function SourceText({ source, medium, campaign, className }: {
  source?: string | null; medium?: string | null; campaign?: string | null; className?: string
}) {
  const parts = [source, medium, campaign].filter((p) => p && p !== "none")
  if (!parts.length) return <span className={cn("text-muted-foreground", className)}>direct</span>
  return (
    <span className={cn("truncate", className)} title={parts.join(" / ")}>
      {parts[0]}
      {parts.slice(1).map((p, i) => <span key={i} className="text-muted-foreground"> / {p}</span>)}
    </span>
  )
}
