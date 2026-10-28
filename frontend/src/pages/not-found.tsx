import { ArrowLeft, Compass } from "lucide-react"
import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"

export function NotFoundPage() {
  return (
    <Empty className="min-h-[60svh]">
      <EmptyHeader>
        <EmptyMedia variant="icon"><Compass /></EmptyMedia>
        <EmptyTitle>Page not found</EmptyTitle>
        <EmptyDescription>This address isn't part of CrawlDoctor.</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button variant="outline" nativeButton={false} render={<Link to="/dashboard" />}><ArrowLeft />Back to the overview</Button>
      </EmptyContent>
    </Empty>
  )
}
