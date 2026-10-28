import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ThemeProvider } from "next-themes"
import { BrowserRouter } from "react-router-dom"
import axios from "axios"

import "./index.css"
import App from "./App.tsx"
import { AuthProvider } from "@/lib/auth"

// Pages load as separate chunks. A tab left open across a deploy asks for chunks the new build no
// longer has, so load the new build instead (at most once a minute, so a real outage can't loop).
window.addEventListener("vite:preloadError", (event) => {
  const last = Number(sessionStorage.getItem("chunk-reload") || 0)
  if (Date.now() - last < 60_000) return
  sessionStorage.setItem("chunk-reload", String(Date.now()))
  event.preventDefault()
  window.location.reload()
})

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      // Don't retry authentication errors: the client signs in through the hub again by itself
      retry: (failures, error) => !(axios.isAxiosError(error) && error.response?.status === 401) && failures < 2,
    },
  },
})

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
