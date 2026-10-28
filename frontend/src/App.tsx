import { lazy, Suspense } from "react"
import { Loader2, ShieldAlert } from "lucide-react"
import { Navigate, Route, Routes } from "react-router-dom"

import { AppSidebar } from "@/components/app-sidebar"
import { SiteHeader } from "@/components/site-header"
import { Button } from "@/components/ui/button"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useAuth } from "@/lib/auth"

// Each page is its own chunk, so the first load only fetches the page being opened
const AiReferralsPage = lazy(() => import("@/pages/ai-referrals").then((m) => ({ default: m.AiReferralsPage })))
const ChannelsPage = lazy(() => import("@/pages/channels").then((m) => ({ default: m.ChannelsPage })))
const CompaniesPage = lazy(() => import("@/pages/companies").then((m) => ({ default: m.CompaniesPage })))
const EmbedPage = lazy(() => import("@/pages/embed").then((m) => ({ default: m.EmbedPage })))
const FunnelsPage = lazy(() => import("@/pages/funnels").then((m) => ({ default: m.FunnelsPage })))
const JourneysPage = lazy(() => import("@/pages/journeys").then((m) => ({ default: m.JourneysPage })))
const LeadsPage = lazy(() => import("@/pages/leads").then((m) => ({ default: m.LeadsPage })))
const LivePage = lazy(() => import("@/pages/live").then((m) => ({ default: m.LivePage })))
const NotFoundPage = lazy(() => import("@/pages/not-found").then((m) => ({ default: m.NotFoundPage })))
const OverviewPage = lazy(() => import("@/pages/overview").then((m) => ({ default: m.OverviewPage })))
const PagesPage = lazy(() => import("@/pages/pages").then((m) => ({ default: m.PagesPage })))
const SessionsPage = lazy(() => import("@/pages/sessions").then((m) => ({ default: m.SessionsPage })))
const TrackingPage = lazy(() => import("@/pages/tracking").then((m) => ({ default: m.TrackingPage })))
const UsersPage = lazy(() => import("@/pages/users").then((m) => ({ default: m.UsersPage })))

/** Nothing renders until the hub has signed the person in; a failed sign-in never shows data. */
function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading, error, retry } = useAuth()
  if (error) {
    return (
      <div className="grid min-h-svh place-items-center p-4">
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon"><ShieldAlert /></EmptyMedia>
            <EmptyTitle>{error}</EmptyTitle>
            <EmptyDescription>CrawlDoctor signs you in through the GTM Hub.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent><Button variant="outline" onClick={retry}>Try again</Button></EmptyContent>
        </Empty>
      </div>
    )
  }
  // Also shown while the browser is being sent to the hub's sign-in page
  if (loading || !user) {
    return <div className="grid min-h-svh place-items-center"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
  }
  return <>{children}</>
}

export default function App() {
  return (
    <TooltipProvider>
      <AuthGate>
        <SidebarProvider>
          <AppSidebar />
          <SidebarInset className="min-w-0">
            <SiteHeader />
            <main className="mx-auto w-full max-w-[1600px] flex-1 space-y-6 px-4 py-6 lg:px-6">
              <Suspense fallback={<div className="grid min-h-64 place-items-center"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>}>
                <Routes>
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                  {/* Sign-in happens in the GTM Hub; keep old /login links working */}
                  <Route path="/login" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/dashboard" element={<OverviewPage />} />
                  <Route path="/live-data" element={<LivePage />} />
                  <Route path="/sessions" element={<SessionsPage />} />
                  <Route path="/users" element={<UsersPage />} />
                  <Route path="/pages" element={<PagesPage />} />
                  <Route path="/channels" element={<ChannelsPage />} />
                  <Route path="/ai-referrals" element={<AiReferralsPage />} />
                  <Route path="/companies" element={<CompaniesPage />} />
                  <Route path="/funnels" element={<FunnelsPage />} />
                  <Route path="/journeys" element={<JourneysPage />} />
                  <Route path="/leads" element={<LeadsPage />} />
                  <Route path="/embed" element={<EmbedPage />} />
                  <Route path="/site-health" element={<TrackingPage />} />
                  <Route path="*" element={<NotFoundPage />} />
                </Routes>
              </Suspense>
            </main>
          </SidebarInset>
        </SidebarProvider>
      </AuthGate>
      <Toaster richColors position="bottom-right" />
    </TooltipProvider>
  )
}
