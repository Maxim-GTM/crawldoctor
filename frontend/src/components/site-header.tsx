import { RefreshCw } from "lucide-react"
import { useIsFetching, useQueryClient } from "@tanstack/react-query"
import { useLocation } from "react-router-dom"

import { CommandSearch } from "@/components/command-search"
import { ThemeToggle } from "@/components/theme-toggle"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { navItem } from "@/lib/nav"
import { cn } from "@/lib/utils"

export function SiteHeader() {
  const { pathname } = useLocation()
  const fetching = useIsFetching()
  const queryClient = useQueryClient()
  const title = navItem(pathname)?.label ?? "Not found"

  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur-md md:rounded-t-xl lg:px-6">
      {/* On desktop the collapse button lives in the sidebar itself; phones need one here to open the drawer. */}
      <SidebarTrigger className="-ml-1.5 md:hidden" />
      <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4 data-[orientation=vertical]:self-center md:hidden" />
      <div className="flex min-w-0 items-center gap-2 text-sm">
        <span className="hidden truncate text-muted-foreground sm:inline">CrawlDoctor</span>
        <span className="hidden text-muted-foreground/50 sm:inline" aria-hidden>/</span>
        <span className="truncate font-medium text-foreground">{title}</span>
      </div>
      <div className="ml-auto flex items-center gap-1">
        <CommandSearch />
        <Tooltip>
          <TooltipTrigger render={<Button variant="ghost" size="icon-sm" aria-label="Refresh data"
            onClick={() => queryClient.invalidateQueries()} />}>
            <RefreshCw className={cn(fetching > 0 && "animate-spin motion-reduce:animate-none")} />
          </TooltipTrigger>
          <TooltipContent side="bottom">{fetching > 0 ? "Loading…" : "Refresh data"}</TooltipContent>
        </Tooltip>
        <ThemeToggle />
      </div>
    </header>
  )
}
