import { useEffect, useState } from 'react'
import { ExternalLinkIcon } from 'lucide-react'
import { getProjects, type ProjectItem, type ProjectSnapshot, type ProjectStatus, type ProjectTaskStatus } from '@/api'
import { Badge } from '@/components/ui/badge'
import { timeAgo } from '@/lib/time-ago'
import { cn } from '@/lib/utils'

const projectLabels: Record<ProjectStatus, string> = { active: 'Active', waiting: 'Waiting', done: 'Done' }
const projectTone: Record<ProjectStatus, string> = {
  active: 'bg-sky-500/15 text-sky-200',
  waiting: 'bg-secondary text-secondary-foreground',
  done: 'bg-emerald-500/15 text-emerald-200',
}
const taskLabels: Record<ProjectTaskStatus, string> = { todo: 'To do', in_progress: 'In progress', blocked: 'Blocked', done: 'Done' }
const taskTone: Record<ProjectTaskStatus, string> = {
  todo: 'bg-secondary text-secondary-foreground',
  in_progress: 'bg-sky-500/15 text-sky-200',
  blocked: 'bg-destructive/15 text-destructive',
  done: 'bg-emerald-500/15 text-emerald-200',
}

const questionCount = (count: number) => `${count} open ${count === 1 ? 'question' : 'questions'}`

function Project({ project }: { project: ProjectItem }) {
  return (
    <article className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-sm font-semibold text-primary">{project.code}</span>
        <h3 className="font-serif text-lg leading-tight">{project.name}</h3>
        <Badge className={cn('ml-auto', projectTone[project.status])}>{projectLabels[project.status]}</Badge>
      </header>

      {project.tasks.length > 0 && (
        <ul className="flex flex-col divide-y divide-border">
          {project.tasks.map((task, index) => (
            <li key={index} className="flex items-center gap-3 py-2 text-sm first:pt-0 last:pb-0">
              <span className="min-w-0 flex-1">{task.title}</span>
              {task.pr_url && (
                <a href={task.pr_url} target="_blank" rel="noreferrer" aria-label="Pull request" className="flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
                  PR<ExternalLinkIcon className="size-3" aria-hidden />
                </a>
              )}
              <Badge className={taskTone[task.status]}>{taskLabels[task.status]}</Badge>
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs text-muted-foreground">{questionCount(project.open_questions)}</p>

      {project.pending_prod_steps.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <h4 className="text-sm font-semibold">Production steps waiting</h4>
          <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed text-foreground/90 marker:text-primary">
            {project.pending_prod_steps.map((step, index) => <li key={index}>{step}</li>)}
          </ul>
        </section>
      )}
    </article>
  )
}

/** grimoire's projects, read-only: Magic Tower shows what grimoire last wrote and edits nothing. */
export function ProjectsView() {
  const [snapshot, setSnapshot] = useState<ProjectSnapshot | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    getProjects().then(setSnapshot).catch(() => setFailed(true))
  }, [])

  return (
    <section aria-label="Projects" className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto bg-card/40 p-6">
      <div>
        <h2 className="font-serif text-2xl leading-tight tracking-tight">Projects</h2>
        {snapshot?.updated_at && <p className="mt-1 text-xs text-muted-foreground">Updated {timeAgo(snapshot.updated_at)}. Read-only: grimoire keeps these up to date.</p>}
      </div>
      {failed && <p className="text-sm text-muted-foreground">Could not load projects.</p>}
      {snapshot && !snapshot.projects.length && <p className="text-sm text-muted-foreground">No projects from grimoire yet.</p>}
      {snapshot?.projects.map(project => <Project key={project.code} project={project} />)}
    </section>
  )
}
