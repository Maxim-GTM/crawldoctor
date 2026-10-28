import axios, { type AxiosResponse } from "axios"

/* ---------- Response shapes (only the fields the dashboard reads) ---------- */

export type Paged = {
  total_count: number
  total_pages: number
  current_page: number
  has_next: boolean
  has_prev: boolean
  error?: string
}

export type HubUser = { id: number; username: string; email: string; full_name?: string; is_superuser: boolean }
export type HubSession = { access_token: string; expires_in: number; user: HubUser; signout_url: string }

export type VisitorSummary = {
  total_visits: number
  unique_visitors: number
  conversions: number
  conversion_rate: number
  visits_by_category: { category: string; count: number }[]
  top_sources: { source: string; count: number }[]
  top_campaigns: { campaign: string; count: number }[]
}

export type Categories = { categories: { name: string; count: number }[] }
export type PageAnalytics = { page_visits: { domain: string; total_visits: number; unique_visitors: number }[] }

export type FunnelStage = { label: string; count: number }
export type FunnelRate = { label: string; rate: number; dropoff_count?: number }
export type Funnel = { key?: string; label: string; stages: FunnelStage[]; rates?: FunnelRate[] }
export type FunnelSummary = { funnels: Funnel[] }

export type FunnelStep = { label: string; type: "page" | "event"; path: string; event_type?: string }
export type FunnelDef = { key: string; label: string; steps: FunnelStep[] }
export type FunnelConfig = { funnels: FunnelDef[] }

export type FunnelTiming = {
  transitions: { from: string; to: string; sample_size: number; avg_seconds: number; median_seconds: number; p90_seconds: number }[]
}
export type FunnelPerson = {
  client_id: string
  source?: string
  medium?: string
  campaign?: string
  entry_page?: string
  entry_referrer?: string
  stage_reached_at?: string
  first_seen?: string
  last_seen?: string
  email?: string
  name?: string
  path_sequence?: string
  has_captured_data?: boolean
  captured_data?: unknown
}
export type FunnelPeople = { users: FunnelPerson[] }

export type Visit = {
  id: number
  timestamp: string
  user_agent: string
  page_url: string
  is_bot: boolean
  crawler_type: string
  country: string
  city: string
  session_id: string
  tracking_id: string
  source: string
  medium: string
  campaign: string
  client_side_language?: string
  client_side_screen_resolution?: string
  client_side_connection_type?: string
  client_side_timezone?: string
}
export type RecentActivity = Paged & { visits: Visit[] }

export type TimelineItem = {
  type: "visit" | "event"
  id: number | string
  timestamp?: string | null
  event_type?: string
  page_url?: string
  crawler_type?: string
  is_bot?: boolean
  source?: string
  medium?: string
  campaign?: string
  country?: string
  city?: string
  tracking_id?: string
  tracking_method?: string
  data?: Record<string, unknown> | null
}
export type Timeline = { timeline: TimelineItem[]; has_next?: boolean; has_prev?: boolean }

export type SessionRow = {
  session_id: string
  client_id?: string | null
  first_visit?: string | null
  last_visit?: string | null
  visit_count: number
  classification?: string
  country?: string
  city?: string
  client_side_language?: string
  client_side_screen_resolution?: string
  client_side_timezone?: string
  entry_referrer_domain?: string
}
export type SessionList = Paged & { sessions: SessionRow[] }
export type SessionFilters = { visitor?: string; country?: string; referrer?: string; hasClientId?: boolean }
export type SessionDetail = { session?: SessionRow; timeline: TimelineItem[] }

export type Attribution = { source?: string; medium?: string; campaign?: string; landing_page?: string }
export type UnifiedUser = {
  client_id: string
  email?: string | null
  name?: string | null
  attribution?: Attribution
  session_count: number
  visit_count: number
  conversion_count: number
  first_seen?: string | null
  last_seen?: string | null
}
export type UserList = Paged & { users: UnifiedUser[] }
export type UserFilters = { q?: string; converted?: boolean; source?: string; visitor?: string }
export type UserActivity = {
  attribution?: Attribution
  summary?: { unique_sessions?: number; total_visits?: number; total_events?: number; unique_domains?: number; conversions?: number }
  sessions?: { session_id: string; city?: string; country?: string; first_visit?: string; last_visit?: string; visit_count: number }[]
  timeline?: TimelineItem[]
}

export type JourneyRow = {
  client_id: string
  source?: string
  campaign?: string
  entry_page?: string
  exit_page?: string
  visit_count?: number
  form_fill_count?: number
  has_captured_data?: boolean
  first_seen?: string | null
  last_seen?: string | null
}
export type JourneyList = Paged & { journeys: JourneyRow[] }
export type JourneySort = "last_seen" | "first_seen" | "visit_count" | "form_fill_count"
export type JourneyFilters = {
  targetPath?: string; withCapturedOnly: boolean; source?: string; campaign?: string; sort?: JourneySort; order?: "asc" | "desc"
}

export type LeadRow = {
  client_id: string
  captured_path?: string
  email?: string
  name?: string
  source?: string
  medium?: string
  campaign?: string
  captured_at?: string | null
  company?: string | null
}
export type LeadList = Paged & { leads: LeadRow[] }
export type FormFill = { id?: number; timestamp?: string; path?: string; page_url?: string; form_values?: unknown }
export type LeadDetail = {
  error?: string
  latest_capture?: { form_values?: unknown }
  url_params?: Record<string, unknown> | null
  form_fills?: FormFill[]
  journey?: Timeline
}

export type LiveEvent = {
  id: number
  timestamp: string
  event_type: string
  page_url: string
  path?: string
  page_domain?: string
  referrer?: string
  client_id?: string
  session_id?: string
  event_data?: Record<string, unknown> | null
  source?: string
  medium?: string
  campaign?: string
  /** From the event's page view; missing when the event has none */
  is_bot?: boolean | null
  crawler_type?: string | null
}

export type RecentFilters = { visitor?: string; path?: string; source?: string; country?: string; domain?: string }

export type FacetField =
  | "visits.source" | "visits.country" | "visits.page_domain" | "visits.crawler_type"
  | "sessions.country" | "sessions.entry_referrer_domain"
  | "leads.captured_path" | "leads.source" | "journeys.source" | "journeys.campaign"
export type Facet = { field: FacetField; values: { value: string; count: number }[] }

export type TimeSeries = { series: { day: string; name: string; count: number }[] }
export type TopPage = { domain: string; path: string; views: number; visitors: number; last_seen?: string | null }
export type TopPages = { pages: TopPage[] }

export type Channel = {
  channel: string; views: number; visitors: number; leads: number
  sources: { source: string; medium?: string | null; views: number }[]
}
export type Channels = { channels: Channel[] }

export type AiReferrals = {
  views: number
  visitors: number
  assistants: { assistant: string; views: number; visitors: number }[]
  pages: { domain: string; path: string; views: number; visitors: number }[]
  daily: { day: string; assistant: string; views: number }[]
  leads: { client_id: string; name?: string | null; email?: string | null; captured_path?: string | null; captured_at?: string | null; assistant?: string | null }[]
}

export type Company = {
  domain: string; name?: string | null; type?: string | null; country?: string | null
  views: number; sessions: number; visitors: number; last_seen?: string | null
  pages: { domain: string; path: string; views: number }[]
}
export type Companies = {
  coverage: { human_sessions: number; enriched_sessions: number; company_sessions: number }
  companies: Company[]
}

export type TrackingStatus = "live" | "quiet" | "stale"
export type TrackedSite = {
  domain: string; ours: boolean; last_seen?: string | null; status: TrackingStatus; views_24h: number; views_7d: number
  tracking_ids: { tracking_id?: string | null; views_30d: number; last_seen?: string | null; status: TrackingStatus }[]
}
export type TrackingHealth = { checked_at: string; sites: TrackedSite[]; hidden_domains: number }

export type SearchResult = {
  kind: "journey" | "session" | "page"; id: string; label: string; detail?: string | null
  domain?: string | null; path?: string | null
}
export type SearchResults = { query: string; results: SearchResult[] }

/* ---------- Client ---------- */

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || window.location.origin,
  timeout: 120000,
  headers: { "Content-Type": "application/json" },
})

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("auth_token")
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

let pendingHubSignIn: Promise<HubSession> | null = null

const requestHubSession = async (): Promise<HubSession> => {
  try {
    const response = await apiClient.get<HubSession>("/api/v1/auth/hub", {
      params: { next: window.location.pathname + window.location.search },
      skipHubRetry: true,
    } as object)
    localStorage.setItem("auth_token", response.data.access_token)
    return response.data
  } catch (error) {
    const res = axios.isAxiosError(error) ? error.response : undefined
    const hubPage = res?.data?.login_url || res?.data?.no_access_url
    if ((res?.status === 401 || res?.status === 403) && hubPage) {
      localStorage.removeItem("auth_token")
      window.location.assign(hubPage)
      return new Promise<HubSession>(() => {})
    }
    throw error
  } finally {
    pendingHubSignIn = null
  }
}

// Swap the GTM Hub session (a cookie the browser sends along) for a CrawlDoctor
// access token. When the hub says the person isn't signed in or has no access,
// the browser is sent to the hub and the returned promise never settles.
export const hubSignIn = (): Promise<HubSession> => {
  if (!pendingHubSignIn) pendingHubSignIn = requestHubSession()
  return pendingHubSignIn
}

// On a 401 (e.g. an expired token), sign in through the hub again once and retry with the new token
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const request = error.config
    if (error.response?.status === 401 && request && !request.skipHubRetry) {
      request.skipHubRetry = true
      await hubSignIn()
      return apiClient(request)
    }
    if (error.response?.status >= 500) console.error("Server error:", error.response?.data)
    return Promise.reject(error)
  },
)

/** Builds a query string, leaving out empty values. */
function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.append(k, String(v))
  return p.toString()
}

const get = async <T,>(path: string, params: Parameters<typeof qs>[0] = {}): Promise<T> =>
  (await apiClient.get<T>(`${path}?${qs(params)}`)).data
const getBlob = (path: string, params: Parameters<typeof qs>[0]): Promise<AxiosResponse<Blob>> =>
  apiClient.get(`${path}?${qs(params)}`, { responseType: "blob" })

export type Range = { start: string; end: string }
const range = (r?: Range) => ({ start_date: r?.start, end_date: r?.end })

export const analyticsAPI = {
  getVisitorSummary: (r: Range) => get<VisitorSummary>("/api/v1/analytics/summary", range(r)),
  getVisitorCategories: (r: Range) => get<Categories>("/api/v1/analytics/categories", range(r)),
  getPageAnalytics: (r: Range) => get<PageAnalytics>("/api/v1/analytics/pages", range(r)),
  getRecentActivity: (r: Range, limit: number, offset: number, f: RecentFilters = {}) =>
    get<RecentActivity>("/api/v1/analytics/recent", { ...range(r), ...f, limit, offset }),
  getFacet: (field: FacetField, r: Range, humansOnly = false) =>
    get<Facet>("/api/v1/analytics/facets", { field, ...range(r), humans_only: humansOnly || undefined }),
  getTimeSeries: (r: Range) => get<TimeSeries>("/api/v1/analytics/timeseries", range(r)),
  getTopPages: (r: Range, f: { humansOnly?: boolean; domain?: string; path?: string; limit?: number } = {}) =>
    get<TopPages>("/api/v1/analytics/top-pages", { ...range(r), humans_only: f.humansOnly ?? true, domain: f.domain, path: f.path, limit: f.limit }),
  getChannels: (r: Range) => get<Channels>("/api/v1/analytics/channels", range(r)),
  getAiReferrals: (r: Range) => get<AiReferrals>("/api/v1/analytics/ai-referrals", range(r)),
  getCompanies: (r: Range) => get<Companies>("/api/v1/analytics/companies", range(r)),
  getTrackingHealth: () => get<TrackingHealth>("/api/v1/analytics/tracking-health"),
  search: (q: string) => get<SearchResults>("/api/v1/analytics/search", { q }),

  getFunnelSummary: (r: Range) => get<FunnelSummary>("/api/v1/analytics/funnels", range(r)),
  getFunnelConfig: () => get<FunnelConfig>("/api/v1/analytics/funnels/config"),
  saveFunnelConfig: async (config: FunnelConfig) => (await apiClient.put("/api/v1/analytics/funnels/config", config)).data,
  getFunnelTiming: (key: string, r: Range) => get<FunnelTiming>(`/api/v1/analytics/funnels/${key}/timing`, range(r)),
  getFunnelDropoffs: (key: string, step: number, r: Range, limit = 50, offset = 0) =>
    get<FunnelPeople>(`/api/v1/analytics/funnels/${key}/dropoffs`, { step, limit, offset, ...range(r) }),
  getFunnelStageUsers: (key: string, step: number, r: Range, limit = 50, offset = 0) =>
    get<FunnelPeople>(`/api/v1/analytics/funnels/${key}/stage-users`, { step, limit, offset, ...range(r) }),

  listSessions: (r: Range, f: SessionFilters, limit: number, offset: number) =>
    get<SessionList>("/api/v1/analytics/sessions", {
      ...range(r), visitor: f.visitor, country: f.country, referrer: f.referrer, has_client_id: f.hasClientId, limit, offset,
    }),
  getSessionDetail: (sessionId: string) => get<SessionDetail>(`/api/v1/analytics/sessions/${sessionId}`),

  listUnifiedUsers: (r: Range, f: UserFilters, limit: number, offset: number) =>
    get<UserList>("/api/v1/analytics/users", {
      ...range(r), q: f.q, converted: f.converted || undefined, source: f.source, visitor: f.visitor, limit, offset,
    }),
  getUnifiedUserActivity: (clientId: string) => get<UserActivity>(`/api/v1/analytics/users/${clientId}`),
  getJourneyTimeline: (clientId: string, limit = 200, offset = 0) =>
    get<Timeline>(`/api/v1/analytics/journeys/${clientId}`, { limit, offset }),

  listJourneys: (f: JourneyFilters & Range, limit: number, offset: number) =>
    get<JourneyList>("/api/v1/analytics/journeys", { ...journeyParams(f), ...range(f), limit, offset }),
  exportJourneysCSV: (f: JourneyFilters & Range) => getBlob("/api/v1/analytics/journeys/export", { ...journeyParams(f), ...range(f) }),

  listLeads: (f: LeadFilters & Range, limit: number, offset: number) =>
    get<LeadList>("/api/v1/analytics/leads", { ...leadParams(f), ...range(f), limit, offset }),
  exportLeadsCSV: (f: LeadFilters & Range) => getBlob("/api/v1/analytics/leads/export", { ...leadParams(f), ...range(f) }),
  getLeadDetail: (clientId: string, limit = 200, offset = 0) =>
    get<LeadDetail>(`/api/v1/analytics/leads/${clientId}`, { limit, offset }),

  exportVisitsCSV: (r: Range) => getBlob("/api/v1/analytics/export/csv", range(r)),
  exportEventsCSV: (r: Range) => getBlob("/api/v1/analytics/export/events.csv", range(r)),
  deleteAllVisits: async () => (await apiClient.delete("/api/v1/analytics/visits/all")).data,

  getLiveEvents: (limit = 100) => get<{ events: LiveEvent[] }>("/api/v1/analytics/live-events", { limit }),
}

export type LeadFilters = { q?: string; capturedPath?: string; source?: string; medium?: string; campaign?: string }
const leadParams = (f: LeadFilters) => ({ q: f.q, captured_path: f.capturedPath, source: f.source, medium: f.medium, campaign: f.campaign })
const journeyParams = (f: JourneyFilters) => ({
  target_path: f.targetPath, with_captured_only: f.withCapturedOnly || undefined, source: f.source, campaign: f.campaign, sort: f.sort, order: f.order,
})

export const adminAPI = {
  rebuildSummaries: async (days = 30) => (await apiClient.post(`/api/v1/admin/rebuild-summaries?days=${days}`)).data,
}

export function apiError(error: unknown): string {
  if (axios.isAxiosError(error)) return error.response?.data?.detail || error.response?.data?.message || error.message
  return error instanceof Error ? error.message : "An unexpected error occurred"
}

/** Saves a CSV response, using the server's filename when it sends one. */
export function saveBlob(response: AxiosResponse<Blob>, fallbackName: string) {
  const disposition: string = response.headers?.["content-disposition"] || ""
  const name = disposition.match(/filename=([^;]+)/i)?.[1]?.replace(/"/g, "") || fallbackName
  const blob = response.data instanceof Blob ? response.data : new Blob([response.data], { type: "text/csv" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
