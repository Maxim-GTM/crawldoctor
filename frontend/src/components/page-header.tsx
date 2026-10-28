import type { ReactNode } from "react"

/** The page's own title block; the top bar carries the crumb. */
export function PageHeader({ title, description, children }: {
  title: string; description?: string; children?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
      <div className="min-w-0 flex-1 basis-64">
        <h1 className="truncate text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {children && <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">{children}</div>}
    </div>
  )
}

export function Page({ children }: { children: ReactNode }) {
  return <div className="space-y-6">{children}</div>
}
