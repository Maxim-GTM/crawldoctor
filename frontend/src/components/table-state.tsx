import type { ReactNode } from "react"
import { AlertCircle } from "lucide-react"

import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { TableCell, TableRow } from "@/components/ui/table"

/** Skeleton rows while a table's first page loads. */
export function LoadingRows({ cols, rows = 8 }: { cols: number; rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, i) => (
        <TableRow key={i} className="hover:bg-transparent"><TableCell colSpan={cols}><Skeleton className="h-8" /></TableCell></TableRow>
      ))}
    </>
  )
}

/** One full-width row holding an empty or error message. */
export function EmptyRow({ cols, icon, title, description, error }: {
  cols: number; icon?: ReactNode; title: string; description?: ReactNode; error?: boolean
}) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={cols} className="whitespace-normal">
        <Empty className="py-8">
          <EmptyHeader>
            <EmptyMedia variant="icon" className={error ? "text-destructive" : undefined}>{error ? <AlertCircle /> : icon}</EmptyMedia>
            <EmptyTitle>{title}</EmptyTitle>
            {description && <EmptyDescription>{description}</EmptyDescription>}
          </EmptyHeader>
        </Empty>
      </TableCell>
    </TableRow>
  )
}
