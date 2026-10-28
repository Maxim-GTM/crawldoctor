import { useSyncExternalStore, type ReactNode } from "react"

const subscribe = () => () => {}

/** Renders its children only when the dashboard is opened on its own address. Inside the GTM Hub's
 * iframe the hub's sidebar already has the account controls, so they aren't repeated here. */
export function StandaloneOnly({ children }: { children: ReactNode }) {
  const standalone = useSyncExternalStore(subscribe, () => window.self === window.top, () => false)
  return standalone ? <>{children}</> : null
}
