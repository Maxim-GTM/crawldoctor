import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react"
import axios from "axios"

import { hubSignIn, type HubUser } from "@/lib/api"

type Auth = {
  user: HubUser | null
  signOutUrl: string | null
  /** The hub's own address, for the "GTM Hub" link. */
  hubUrl: string
  error: string | null
  loading: boolean
  retry: () => void
  signOut: () => void
}

const AuthContext = createContext<Auth | undefined>(undefined)

export function useAuth(): Auth {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider")
  return ctx
}

/**
 * Signs in through the GTM Hub on every page load, so a hub sign-out or a revoked dashboard applies
 * as soon as the page is opened again. People who aren't signed in (or have no access) are sent to
 * the hub instead.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<HubUser | null>(null)
  const [signOutUrl, setSignOutUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const signIn = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const session = await hubSignIn()
      setUser(session.user)
      setSignOutUrl(session.signout_url)
    } catch (err) {
      console.error("Hub sign-in failed:", err)
      const status = axios.isAxiosError(err) ? err.response?.status : undefined
      setError(status === 503 ? "The sign-in service is unavailable. Try again shortly." : "We couldn't sign you in.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { signIn() }, [signIn])

  let hubUrl = "https://hub.agitracker.io"
  try { if (signOutUrl) hubUrl = new URL(signOutUrl).origin } catch { /* keep the default */ }

  return (
    <AuthContext.Provider value={{
      user, signOutUrl, hubUrl, error, loading, retry: signIn,
      // The "Sign out" link then takes the browser to the hub's sign-out page
      signOut: () => localStorage.removeItem("auth_token"),
    }}>
      {children}
    </AuthContext.Provider>
  )
}
