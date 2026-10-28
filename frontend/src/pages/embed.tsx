import { useState } from "react"
import { Activity, ArrowRight, Bot, CheckCircle2, UserRound } from "lucide-react"
import { Link } from "react-router-dom"

import { CopyButton } from "@/components/client-id"
import { Page, PageHeader } from "@/components/page-header"
import { KindDot } from "@/components/visitor-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { describe } from "@/lib/nav"

function CodeBlock({ code }: { code: string }) {
  return (
    <div className="relative rounded-lg border bg-muted/50">
      <pre className="overflow-x-auto p-3 pr-12 font-mono text-[12.5px] leading-relaxed whitespace-pre"><code>{code}</code></pre>
      <CopyButton value={code} label="Copy code" className="absolute top-2 right-2 bg-background/80 backdrop-blur" />
    </div>
  )
}

function Steps({ steps }: { steps: React.ReactNode[] }) {
  return (
    <ol className="space-y-2 text-sm">
      {steps.map((s, i) => (
        <li key={i} className="flex gap-3">
          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-medium tabular-nums">{i + 1}</span>
          <span className="pt-px">{s}</span>
        </li>
      ))}
    </ol>
  )
}

const PLATFORMS = [
  { name: "Shopify", where: "Online Store → Themes → Edit code → theme.liquid, inside <head>" },
  { name: "Squarespace", where: "Settings → Advanced → Code Injection → Header" },
  { name: "Wix", where: "Settings → Custom Code → Add Custom Code → Head" },
  { name: "Webflow", where: "Site settings → Custom code → Head code" },
]

export function EmbedPage() {
  const [trackingId, setTrackingId] = useState("your-website")
  const tid = encodeURIComponent(trackingId.trim() || "your-website")
  const snippet = `<!-- CrawlDoctor JavaScript Tracking -->\n<script src="${window.location.origin}/track/js?tid=${tid}" async></script>`

  return (
    <>
      <PageHeader title="Install tracking" description={describe("/embed")} />
      <Page>
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Your tracking code</CardTitle>
              <CardDescription>Async, so it never blocks the page. It records page views, clicks and form submissions.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field className="max-w-sm gap-1.5">
                <FieldLabel htmlFor="tracking-id">Tracking ID</FieldLabel>
                <Input id="tracking-id" className="font-mono text-[13px]" value={trackingId} onChange={(e) => setTrackingId(e.target.value)} placeholder="blog, main-site, landing-page" />
                <FieldDescription>A short name for the site, so you can tell sites apart in the data.</FieldDescription>
              </Field>
              <CodeBlock code={snippet} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>What it separates</CardTitle>
              <CardDescription>Every visit is sorted as it arrives</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="space-y-1.5">
                <div className="flex items-center gap-2 font-medium"><Bot className="size-4 text-muted-foreground" />Crawlers and bots</div>
                <ul className="space-y-1 pl-6 text-muted-foreground">
                  <li className="flex gap-2"><KindDot kind="ai" className="mt-1.5" />AI: GPTBot, ChatGPT-User, ClaudeBot, PerplexityBot…</li>
                  <li className="flex gap-2"><KindDot kind="search" className="mt-1.5" />Search: Googlebot, Bingbot</li>
                  <li className="flex gap-2"><KindDot kind="bot" className="mt-1.5" />Other and unknown bots</li>
                </ul>
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center gap-2 font-medium"><UserRound className="size-4 text-muted-foreground" />People</div>
                <ul className="space-y-1 pl-6 text-muted-foreground">
                  <li className="flex gap-2"><KindDot kind="human" className="mt-1.5" />Desktop and mobile browsers, with UTM source and campaign</li>
                </ul>
              </div>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Add it to your site</CardTitle>
            <CardDescription>Put the code in the &lt;head&gt; of every page you want tracked</CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="html" className="gap-4">
              <TabsList>
                <TabsTrigger value="html">HTML</TabsTrigger>
                <TabsTrigger value="ghost">Ghost</TabsTrigger>
                <TabsTrigger value="wordpress">WordPress</TabsTrigger>
                <TabsTrigger value="other">Other platforms</TabsTrigger>
              </TabsList>
              <TabsContent value="html" className="space-y-3">
                <p className="text-sm text-muted-foreground">Paste it anywhere inside <code className="rounded bg-muted px-1 font-mono text-xs">&lt;head&gt;</code> on each page, or in your shared layout.</p>
                <CodeBlock code={`<head>\n  …\n  ${snippet.replace("\n", "\n  ")}\n</head>`} />
              </TabsContent>
              <TabsContent value="ghost" className="space-y-3">
                <Steps steps={["Open Ghost Admin", "Go to Settings → Code injection", "Paste the code into Site header", "Save"]} />
                <CodeBlock code={snippet} />
              </TabsContent>
              <TabsContent value="wordpress" className="space-y-3">
                <Steps steps={[
                  "Go to Appearance → Theme File Editor (or use a header-scripts plugin)",
                  "Open header.php of your active theme",
                  <>Paste the code just before <code className="rounded bg-muted px-1 font-mono text-xs">&lt;/head&gt;</code></>,
                  "Update the file",
                ]} />
                <CodeBlock code={snippet} />
              </TabsContent>
              <TabsContent value="other">
                <dl className="divide-y rounded-lg border text-sm">
                  {PLATFORMS.map((p) => (
                    <div key={p.name} className="grid gap-1 p-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
                      <dt className="font-medium">{p.name}</dt>
                      <dd className="text-muted-foreground">{p.where}</dd>
                    </div>
                  ))}
                </dl>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="flex flex-wrap items-center gap-4">
            <CheckCircle2 className="size-5 shrink-0 text-good" />
            <div className="min-w-0 flex-1">
              <div className="font-medium">Check it works</div>
              <p className="text-sm text-muted-foreground">Open a page on your site, then watch the visit arrive in Live events within a few seconds.</p>
            </div>
            <Button variant="outline" size="sm" nativeButton={false} render={<Link to="/live-data" />}><Activity />Open Live events<ArrowRight /></Button>
          </CardContent>
        </Card>
      </Page>
    </>
  )
}
