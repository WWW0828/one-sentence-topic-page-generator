import { useEffect, useMemo, useState } from 'react'
import { EVENT_TYPES } from '../types'
import type { TopicPageData, FactRow, TimelineRow, VerificationStatus, SourceItem, EntityRow } from '../types'

interface ReviewPanelProps {
  page: TopicPageData
  hasOriginal: boolean
  isGenerating: boolean
  onCommitEdits: (edited: TopicPageData) => void
  onFetchOriginal: () => Promise<TopicPageData | null>
}

// Each editable row tracks a "rejected" flag; rejected rows are dropped on commit.
interface EditableFact extends FactRow { rejected: boolean }
interface EditableTimeline extends TimelineRow { rejected: boolean }
interface EditableEntity extends EntityRow { rejected: boolean }

export function ReviewPanel({ page, hasOriginal, isGenerating, onCommitEdits, onFetchOriginal }: ReviewPanelProps) {
  const [title, setTitle] = useState(page.title)
  const [summary, setSummary] = useState(page.summary)
  const [eventType, setEventType] = useState(page.event_type)
  const [facts, setFacts] = useState<EditableFact[]>([])
  const [timeline, setTimeline] = useState<EditableTimeline[]>([])
  const [entities, setEntities] = useState<EditableEntity[]>([])

  // Re-seed local edit state whenever a fresh page arrives (new generation or re-render).
  useEffect(() => {
    setTitle(page.title)
    setSummary(page.summary)
    setEventType(page.event_type)
    setFacts(page.key_facts.map(f => ({ ...f, rejected: false })))
    setTimeline(page.timeline.map(t => ({ ...t, rejected: false })))
    setEntities(page.entities.map(e => ({ ...e, rejected: false })))
  }, [page])

  const sourcesById = useMemo(() => {
    const m = new Map<number, SourceItem>()
    for (const s of page.sources) m.set(s.id, s)
    return m
  }, [page.sources])

  const dirty =
    title !== page.title ||
    summary !== page.summary ||
    eventType !== page.event_type ||
    facts.some((f, i) => f.rejected || f.label !== page.key_facts[i]?.label || f.value !== page.key_facts[i]?.value) ||
    timeline.some((t, i) => t.rejected || t.date !== page.timeline[i]?.date || t.description !== page.timeline[i]?.description) ||
    entities.some((e, i) => e.rejected || e.name !== page.entities[i]?.name || e.role !== page.entities[i]?.role || e.type !== page.entities[i]?.type)

  const keptFacts = facts.filter(f => !f.rejected).length
  const keptTimeline = timeline.filter(t => !t.rejected).length
  const keptEntities = entities.filter(e => !e.rejected).length

  const handleApply = () => {
    const edited: TopicPageData = {
      ...page,
      title: title.trim() || page.title,
      summary: summary.trim(),
      event_type: eventType,
      key_facts: facts.filter(f => !f.rejected).map(({ rejected, ...f }) => f),
      timeline: timeline.filter(t => !t.rejected).map(({ rejected, ...t }) => t),
      entities: entities.filter(e => !e.rejected).map(({ rejected, ...e }) => e),
    }
    onCommitEdits(edited)
  }

  // Load the verifier's pre-edit output back into the form only. Nothing is saved and
  // nothing re-renders until the user clicks Apply.
  const handleRevert = async () => {
    const original = await onFetchOriginal()
    if (!original) return
    setTitle(original.title)
    setSummary(original.summary)
    setEventType(original.event_type)
    setFacts(original.key_facts.map(f => ({ ...f, rejected: false })))
    setTimeline(original.timeline.map(t => ({ ...t, rejected: false })))
    setEntities(original.entities.map(e => ({ ...e, rejected: false })))
  }

  return (
    <div className="flex flex-col gap-4 flex-1">
      <p className="text-xs text-gray-500 leading-relaxed">
        Editing the structured data, not the HTML. Reject shaky claims or fix wording, then
        re-render. Each row shows its verification status and the sources behind it.
      </p>

      <Field label="Title">
        <input
          className="w-full text-sm border border-gray-200 rounded-md px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-800"
          value={title}
          onChange={e => setTitle(e.target.value)}
          disabled={isGenerating}
        />
      </Field>

      <Field label="Event Type">
        <select
          className="w-full text-sm border border-gray-200 rounded-md px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-800"
          value={eventType}
          onChange={e => setEventType(e.target.value)}
          disabled={isGenerating}
        >
          {EVENT_TYPES.map(t => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        {eventType !== page.event_type && (
          <p className="text-[11px] text-amber-700 leading-snug">
            ⚠ Changing the type re-frames the page's layout and mood, but the event-specific
            data block was extracted for "{page.event_type}" — it won't be re-extracted.
          </p>
        )}
      </Field>

      <Field label="Summary">
        <textarea
          className="w-full text-sm border border-gray-200 rounded-md px-2.5 py-1.5 resize-none focus:outline-none focus:ring-2 focus:ring-blue-800"
          rows={3}
          value={summary}
          onChange={e => setSummary(e.target.value)}
          disabled={isGenerating}
        />
      </Field>

      <Field label={`Key Facts (${keptFacts}/${facts.length} kept)`}>
        <div className="flex flex-col gap-2">
          {facts.map((f, i) => (
            <RowCard key={i} rejected={f.rejected} verification={f.verification} note={f.note}
              sources={f.source_ids.map(id => sourcesById.get(id)).filter(Boolean) as SourceItem[]}
              onToggleReject={() => setFacts(prev => prev.map((x, j) => j === i ? { ...x, rejected: !x.rejected } : x))}
              disabled={isGenerating}
            >
              <input
                className="w-1/3 text-xs font-medium border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-800"
                value={f.label}
                onChange={e => setFacts(prev => prev.map((x, j) => j === i ? { ...x, label: e.target.value } : x))}
                disabled={isGenerating || f.rejected}
              />
              <input
                className="flex-1 text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-800"
                value={f.value}
                onChange={e => setFacts(prev => prev.map((x, j) => j === i ? { ...x, value: e.target.value } : x))}
                disabled={isGenerating || f.rejected}
              />
            </RowCard>
          ))}
        </div>
      </Field>

      <Field label={`Timeline (${keptTimeline}/${timeline.length} kept)`}>
        <div className="flex flex-col gap-2">
          {timeline.map((t, i) => (
            <RowCard key={i} rejected={t.rejected} verification={t.verification} note={t.note}
              sources={t.source_ids.map(id => sourcesById.get(id)).filter(Boolean) as SourceItem[]}
              onToggleReject={() => setTimeline(prev => prev.map((x, j) => j === i ? { ...x, rejected: !x.rejected } : x))}
              disabled={isGenerating}
            >
              <input
                className="w-28 text-xs font-medium border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-800"
                value={t.date}
                onChange={e => setTimeline(prev => prev.map((x, j) => j === i ? { ...x, date: e.target.value } : x))}
                disabled={isGenerating || t.rejected}
              />
              <input
                className="flex-1 text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-800"
                value={t.description}
                onChange={e => setTimeline(prev => prev.map((x, j) => j === i ? { ...x, description: e.target.value } : x))}
                disabled={isGenerating || t.rejected}
              />
            </RowCard>
          ))}
        </div>
      </Field>

      <Field label={`Key Entities (${keptEntities}/${entities.length} kept)`}>
        <div className="flex flex-col gap-2">
          {entities.map((en, i) => (
            <div key={i} className={`flex items-center gap-2 rounded-md border p-2 ${en.rejected ? 'border-red-200 bg-red-50 opacity-60' : 'border-gray-200 bg-white'}`}>
              <input
                className="w-1/3 text-xs font-medium border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-800"
                value={en.name}
                onChange={e => setEntities(prev => prev.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
                disabled={isGenerating || en.rejected}
              />
              <input
                className="flex-1 text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-800"
                value={en.role}
                onChange={e => setEntities(prev => prev.map((x, j) => j === i ? { ...x, role: e.target.value } : x))}
                disabled={isGenerating || en.rejected}
              />
              <select
                className="text-xs border border-gray-200 rounded px-1.5 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-blue-800"
                value={en.type}
                onChange={e => setEntities(prev => prev.map((x, j) => j === i ? { ...x, type: e.target.value as EntityRow['type'] } : x))}
                disabled={isGenerating || en.rejected}
              >
                <option value="person">person</option>
                <option value="org">org</option>
                <option value="location">location</option>
              </select>
              <button
                onClick={() => setEntities(prev => prev.map((x, j) => j === i ? { ...x, rejected: !x.rejected } : x))}
                disabled={isGenerating}
                title={en.rejected ? 'Restore' : 'Reject (exclude from page)'}
                className={`flex-shrink-0 text-xs px-2 py-1 rounded border transition-colors ${
                  en.rejected
                    ? 'border-gray-300 text-gray-600 hover:bg-gray-100'
                    : 'border-red-200 text-red-600 hover:bg-red-50'
                }`}
              >
                {en.rejected ? 'Restore' : 'Reject'}
              </button>
            </div>
          ))}
        </div>
      </Field>

      <div className="flex items-center gap-2">
        <button
          onClick={handleApply}
          disabled={isGenerating || !dirty}
          className="flex items-center gap-2 px-4 py-2.5 rounded-md text-sm font-medium text-white bg-blue-800 hover:bg-blue-900 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {isGenerating ? 'Re-rendering…' : 'Apply edits & re-render'}
        </button>
        {hasOriginal && (
          <button
            onClick={handleRevert}
            disabled={isGenerating}
            title="Load the pre-edit content back into this form. Click Apply to save and re-render."
            className="px-4 py-2.5 rounded-md text-sm font-medium text-gray-600 border border-gray-200 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ↺ Revert to original
          </button>
        )}
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-semibold text-gray-700 uppercase tracking-wide">{label}</label>
      {children}
    </div>
  )
}

interface RowCardProps {
  rejected: boolean
  verification: VerificationStatus
  note?: string | null
  sources: SourceItem[]
  onToggleReject: () => void
  disabled: boolean
  children: React.ReactNode
}

function RowCard({ rejected, verification, note, sources, onToggleReject, disabled, children }: RowCardProps) {
  return (
    <div className={`flex flex-col gap-1.5 rounded-md border p-2 ${rejected ? 'border-red-200 bg-red-50 opacity-60' : 'border-gray-200 bg-white'}`}>
      <div className="flex items-center gap-2">
        {children}
        <button
          onClick={onToggleReject}
          disabled={disabled}
          title={rejected ? 'Restore' : 'Reject (exclude from page)'}
          className={`flex-shrink-0 text-xs px-2 py-1 rounded border transition-colors ${
            rejected
              ? 'border-gray-300 text-gray-600 hover:bg-gray-100'
              : 'border-red-200 text-red-600 hover:bg-red-50'
          }`}
        >
          {rejected ? 'Restore' : 'Reject'}
        </button>
      </div>
      <div className="flex items-center gap-2 flex-wrap pl-0.5">
        <VerifyTag status={verification} />
        {sources.map(s => (
          <a key={s.id} href={s.url} target="_blank" rel="noreferrer"
            className="text-[11px] text-gray-500 hover:text-blue-700 hover:underline"
            title={s.title}>
            [{s.id}] {s.publisher}
          </a>
        ))}
        {sources.length === 0 && <span className="text-[11px] text-gray-400 italic">no citation</span>}
        {note && <span className="text-[11px] text-amber-700">⚠ {note}</span>}
      </div>
    </div>
  )
}

function VerifyTag({ status }: { status: VerificationStatus }) {
  const map: Record<VerificationStatus, string> = {
    confirmed: 'bg-green-50 text-green-700 border-green-200',
    single_source: 'bg-gray-50 text-gray-600 border-gray-200',
    conflicted: 'bg-amber-50 text-amber-700 border-amber-200',
    unverified: 'bg-red-50 text-red-600 border-red-200',
  }
  const label: Record<VerificationStatus, string> = {
    confirmed: 'confirmed',
    single_source: '1 source',
    conflicted: 'conflicted',
    unverified: 'unverified',
  }
  return (
    <span className={`text-[11px] px-1.5 py-0.5 rounded-full border font-medium ${map[status]}`}>
      {label[status]}
    </span>
  )
}
