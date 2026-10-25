import type { ReactNode } from 'react'
import { TriangleAlertIcon } from 'lucide-react'
import type { Analysis } from '@/api'
import { Badge } from '@/components/ui/badge'
import { timeAgo } from '@/lib/time-ago'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  )
}

const Prose = ({ text }: { text: string }) => <p className="text-sm leading-relaxed whitespace-pre-line text-foreground/90">{text}</p>

// Every string below comes from a model reading untrusted text: it is rendered as React text, never as markup.

/** grimoire's summary, when it was written, and the hint that the source has moved on. */
export function AnalysisSummary({ analysis }: { analysis: Analysis }) {
  return (
    <>
      <p className="mt-3 leading-relaxed whitespace-pre-line">{analysis.summary}</p>
      <p className="mt-2 text-xs text-muted-foreground">Analysed {timeAgo(analysis.analyzed_at)} by {analysis.analyzer}</p>
      {analysis.stale && (
        <p role="note" className="mt-3 flex items-center gap-2 rounded-md bg-primary/10 px-3 py-2 text-xs text-secondary-foreground">
          <TriangleAlertIcon className="size-3.5 shrink-0 text-primary" aria-hidden />
          The source changed since this was analysed.
        </p>
      )}
    </>
  )
}

/** The sections of the analysis' details; the optional ones appear only when they have content. */
export function AnalysisDetails({ analysis }: { analysis: Analysis }) {
  const { asked, systems, known, next_step, open_questions } = analysis.details
  return (
    <div className="flex flex-col gap-5 rounded-xl border border-border bg-card p-5">
      <Section title="Asked"><Prose text={asked} /></Section>
      {systems.length > 0 && (
        <Section title="Systems">
          <ul className="flex flex-wrap gap-1.5">{systems.map((system, index) => <li key={index}><Badge>{system}</Badge></li>)}</ul>
        </Section>
      )}
      {known && <Section title="What's known"><Prose text={known} /></Section>}
      {next_step && <Section title="Next step"><Prose text={next_step} /></Section>}
      {open_questions.length > 0 && (
        <Section title="Open questions">
          <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed text-foreground/90 marker:text-primary">
            {open_questions.map((question, index) => <li key={index}>{question}</li>)}
          </ul>
        </Section>
      )}
    </div>
  )
}
