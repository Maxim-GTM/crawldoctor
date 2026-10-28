import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { TooltipProvider } from "@/components/ui/tooltip"
import { analyticsAPI } from "@/lib/api"
import { FunnelsPage } from "@/pages/funnels"

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  analyticsAPI: {
    getFunnelSummary: vi.fn(),
    getFunnelConfig: vi.fn(),
    saveFunnelConfig: vi.fn(),
    getFunnelTiming: vi.fn(),
    getFunnelDropoffs: vi.fn(),
    getFunnelStageUsers: vi.fn(),
  },
}))

const api = vi.mocked(analyticsAPI)

const renderPage = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TooltipProvider><FunnelsPage /></TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("Funnels page", () => {
  beforeEach(() => {
    api.getFunnelSummary.mockResolvedValue({
      funnels: [{
        key: "demo",
        label: "Demo Funnel",
        stages: [{ label: "Visited /demo", count: 10 }, { label: "Submitted form", count: 2 }],
        rates: [{ label: "Visited /demo → Submitted form", rate: 20, dropoff_count: 8 }],
      }],
    })
    api.getFunnelConfig.mockResolvedValue({
      funnels: [{
        key: "demo",
        label: "Demo Funnel",
        steps: [
          { label: "Visited /demo", type: "page", path: "/demo" },
          { label: "Submitted form", type: "event", path: "/demo", event_type: "form_submit" },
        ],
      }],
    })
    api.getFunnelTiming.mockResolvedValue({
      transitions: [{ from: "Visited /demo", to: "Submitted form", sample_size: 2, avg_seconds: 30, median_seconds: 25, p90_seconds: 40 }],
    })
    api.getFunnelDropoffs.mockResolvedValue({ users: [] })
    api.getFunnelStageUsers.mockResolvedValue({ users: [] })
    api.saveFunnelConfig.mockResolvedValue({})
  })

  it("renders funnel analytics and saves config changes", async () => {
    renderPage()

    expect((await screen.findAllByText("Demo Funnel")).length).toBeGreaterThan(0)
    expect(screen.getByText("8 dropped off")).toBeInTheDocument()
    expect(screen.getByText("20.0%")).toBeInTheDocument()
    expect(await screen.findByText("25s")).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: /configure funnels/i }))

    const labelInput = (await screen.findAllByDisplayValue("Demo Funnel")).find((el) => el.tagName === "INPUT") as HTMLInputElement
    await user.clear(labelInput)
    await user.type(labelInput, "Demo Funnel Updated")
    await user.click(screen.getByRole("button", { name: /save funnels/i }))

    await waitFor(() => expect(api.saveFunnelConfig).toHaveBeenCalledWith({
      funnels: [expect.objectContaining({ key: "demo", label: "Demo Funnel Updated" })],
    }))
  })
})
