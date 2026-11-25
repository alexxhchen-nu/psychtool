import type { ReactNode } from 'react'

interface ReportColumnsProps {
  rail: ReactNode
  editor: ReactNode
  source: ReactNode
}

/**
 * PT-10 three-column shell: sections rail | editor | source card. The editor
 * is always rendered as a sibling of the source column, never behind a modal.
 */
export default function ReportColumns({ rail, editor, source }: ReportColumnsProps) {
  return (
    <div className="report-grid">
      {rail}
      {editor}
      <aside className="review-panel" aria-label="Sources and review">
        {source}
      </aside>
    </div>
  )
}
