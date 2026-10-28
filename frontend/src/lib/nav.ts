import {
  Activity, Building2, Code2, FileText, Filter, History, Inbox, LayoutDashboard, RadioTower, Route, Sparkles, Users, Waypoints,
} from "lucide-react"

export type NavItem = { path: string; label: string; icon: typeof Activity; description: string }

/** The sidebar, top-bar crumb and page titles all read from here. */
export const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Traffic",
    items: [
      { path: "/dashboard", label: "Overview", icon: LayoutDashboard, description: "Who visited: humans, AI crawlers, search engines and other bots, and how they converted" },
      { path: "/live-data", label: "Live events", icon: Activity, description: "Tracking events as they arrive, newest first (heartbeats are left out)" },
      { path: "/sessions", label: "Sessions", icon: History, description: "Every browsing session, most recent first" },
      { path: "/users", label: "Users", icon: Users, description: "People followed across sessions and domains by their persistent client ID" },
      { path: "/pages", label: "Pages", icon: FileText, description: "The pages people view most, by path, with unique visitors" },
    ],
  },
  {
    group: "Acquisition",
    items: [
      { path: "/channels", label: "Channels", icon: Waypoints, description: "Where people come from: search, AI assistants, social, referrals, paid, direct and our own sites" },
      { path: "/ai-referrals", label: "AI referrals", icon: Sparkles, description: "Visits, landing pages and leads sent by ChatGPT, Perplexity, Claude, Gemini and Copilot" },
      { path: "/companies", label: "Companies", icon: Building2, description: "Organisations behind human visits, from IP lookups (ISPs, hosting, VPNs and proxies left out)" },
    ],
  },
  {
    group: "Conversion",
    items: [
      { path: "/funnels", label: "Funnels", icon: Filter, description: "Conversion paths, how long each step takes, and who dropped off" },
      { path: "/journeys", label: "Journeys", icon: Route, description: "From first touch to conversion, with every form a person filled in" },
      { path: "/leads", label: "Leads", icon: Inbox, description: "Captured form submissions with their full journey" },
    ],
  },
  {
    group: "Setup",
    items: [
      { path: "/embed", label: "Install tracking", icon: Code2, description: "Add one script tag to a site to start tracking it" },
      { path: "/site-health", label: "Tracking health", icon: RadioTower, description: "When each site and tracking ID last sent a page view, so a silent tracker stands out" },
    ],
  },
]

export const NAV_ITEMS = NAV.flatMap((g) => g.items)

export const navItem = (pathname: string) => NAV_ITEMS.find((n) => pathname === n.path || pathname.startsWith(`${n.path}/`))

/** A page's one-line description, for its header. */
export const describe = (path: string) => navItem(path)?.description
