import type { ReactNode } from "react"
import { ArrowUpRight, LogOut, PanelLeftIcon } from "lucide-react"
import { Link, useLocation } from "react-router-dom"

import { BifrostMark, BifrostWordmark } from "@/components/bifrost-logo"
import { StandaloneOnly } from "@/components/standalone-only"
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel,
  SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarTrigger, useSidebar,
} from "@/components/ui/sidebar"
import { useAuth } from "@/lib/auth"
import { NAV, navItem } from "@/lib/nav"

/** Group label that keeps its row on the icon rail (fading to a hairline), so icons never shift. */
function RailLabel({ children }: { children: ReactNode }) {
  return (
    <SidebarGroupLabel className="relative group-data-[collapsible=icon]:mt-0 group-data-[collapsible=icon]:opacity-100">
      <span className="sidebar-fade">{children}</span>
      <span aria-hidden className="sidebar-rail-rule absolute top-1/2 left-2 h-px w-4 bg-sidebar-border" />
    </SidebarGroupLabel>
  )
}

/**
 * Sidebar header: [logo link] [collapse button]. Nothing moves between states: on the rail the link
 * narrows to its square, the collapse button fades out where it stands, and the mark becomes the
 * "open" button, swapping to the panel icon on hover. Same treatment as the hub and its other dashboards.
 */
function SidebarBrand() {
  const { state, isMobile, toggleSidebar } = useSidebar()
  const collapsed = state === "collapsed" && !isMobile
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton size="lg" tooltip="Open sidebar"
            className="group/brand hover:bg-transparent active:bg-transparent group-data-[collapsible=icon]:h-12! group-data-[collapsible=icon]:p-2!"
            render={<Link to="/dashboard" role={collapsed ? "button" : undefined}
              aria-label={collapsed ? "Open sidebar" : "CrawlDoctor, overview"}
              onClick={(e) => { if (!collapsed) return; e.preventDefault(); toggleSidebar() }} />}>
            <span className="group/mark relative flex h-8 w-4 shrink-0 items-center justify-center before:absolute before:-inset-x-2 before:inset-y-0 before:rounded-md before:bg-sidebar-accent before:opacity-0 before:transition-opacity before:duration-150 group-data-[collapsible=icon]:group-hover/mark:before:opacity-100 group-data-[collapsible=icon]:group-focus-visible/brand:before:opacity-100">
              <BifrostMark className="relative h-5! w-auto! transition-opacity duration-150 group-data-[collapsible=icon]:group-hover/mark:opacity-0 group-data-[collapsible=icon]:group-focus-visible/brand:opacity-0" />
              <PanelLeftIcon aria-hidden className="absolute text-muted-foreground opacity-0 transition-opacity duration-150 group-data-[collapsible=icon]:group-hover/mark:opacity-100 group-data-[collapsible=icon]:group-focus-visible/brand:opacity-100" />
            </span>
            <span className="sidebar-fade grid flex-1 gap-1 text-left leading-tight">
              <BifrostWordmark className="h-3.5! w-auto! justify-self-start" />
              <span className="truncate text-xs text-muted-foreground">CrawlDoctor</span>
            </span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
      <SidebarTrigger className="sidebar-fade-hide text-muted-foreground" />
    </div>
  )
}

export function AppSidebar() {
  const { isMobile, setOpenMobile } = useSidebar()
  const { pathname } = useLocation()
  const { user, signOutUrl, hubUrl, signOut } = useAuth()
  const active = navItem(pathname)?.path

  return (
    <Sidebar variant="inset" collapsible="icon">
      {/* The outer box is cut off by the moving sidebar edge; the inner one keeps the expanded width in both
          states, so opening and closing never reflows or squeezes anything in here. */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="flex min-h-0 w-full flex-1 flex-col md:w-[calc(var(--sidebar-width)-1rem)]">
          <SidebarHeader>
            <SidebarBrand />
          </SidebarHeader>

          <SidebarContent>
            {NAV.map((g) => (
              <SidebarGroup key={g.group}>
                <RailLabel>{g.group}</RailLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {g.items.map((n) => (
                      <SidebarMenuItem key={n.path}>
                        <SidebarMenuButton isActive={active === n.path} tooltip={n.label}
                          render={<Link to={n.path} onClick={() => { if (isMobile) setOpenMobile(false) }} />}>
                          <n.icon className="size-4" />
                          <span className="sidebar-fade flex-1 truncate">{n.label}</span>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    ))}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            ))}
          </SidebarContent>

          {/* Inside the hub its own sidebar has these; only the standalone address shows them. */}
          <StandaloneOnly>
            <SidebarFooter>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton tooltip="GTM Hub" render={<a href={hubUrl} target="_top" />}>
                    <ArrowUpRight />
                    <span className="sidebar-fade">GTM Hub</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                {signOutUrl && (
                  <SidebarMenuItem>
                    <SidebarMenuButton tooltip={user?.email ? `Sign out ${user.email}` : "Sign out"}
                      render={<a href={signOutUrl} target="_top" onClick={signOut} />}>
                      <LogOut />
                      <span className="sidebar-fade truncate">
                        Sign out{user?.email && <span className="text-muted-foreground"> · {user.email}</span>}
                      </span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )}
              </SidebarMenu>
            </SidebarFooter>
          </StandaloneOnly>
        </div>
      </div>
    </Sidebar>
  )
}
