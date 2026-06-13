export type Provider = 'claude' | 'gemini'
export type SearchSource = 'tavily'
export type StepStatus = 'pending' | 'running' | 'done' | 'error'

// Single source of truth for event classes on the frontend.
// Mirrors the EventType enum in backend/schemas/topic_page.py.
export const EVENT_TYPES = ['sports', 'tech', 'business', 'disaster', 'cultural', 'political', 'other'] as const
export type EventType = (typeof EVENT_TYPES)[number]

export type Verdict = 'ok' | 'ambiguous' | 'refuse'

export interface Step1Result {
  event_type: string
  suggested_title: string
  entities: string[]
  confidence: number
  verdict?: Verdict
  reason?: string
  interpretations?: string[]
}

export interface BlockedState {
  verdict: 'ambiguous' | 'refuse'
  reason: string
  interpretations: string[]
}

export type VerificationStatus = 'confirmed' | 'single_source' | 'unverified' | 'conflicted'

export interface FactRow {
  label: string
  value: string
  source_ids: number[]
  verification: VerificationStatus
  note?: string | null
}

export interface TimelineRow {
  date: string
  description: string
  source_ids: number[]
  verification: VerificationStatus
  note?: string | null
}

export interface SourceItem {
  id: number
  title: string
  url: string
  publisher: string
  date: string
}

export interface EntityRow {
  name: string
  role: string
  type: 'person' | 'org' | 'location'
}

// The full structured page. Fields not edited in the review panel (entities, event-specific
// blocks) are carried through verbatim, so this keeps an index signature.
export interface TopicPageData {
  title: string
  summary: string
  event_type: string
  last_updated: string
  key_facts: FactRow[]
  timeline: TimelineRow[]
  entities: EntityRow[]
  sources: SourceItem[]
  [key: string]: unknown
}

export interface Step2Result {
  queries: string[]
}

export interface Step3Source {
  title: string
  publisher: string
  url: string
}

export interface Step3Result {
  source_count: number
  sources: Step3Source[]
}

export interface Step4Result {
  title: string
  key_facts_count: number
  timeline_count: number
  entities_count: number
  sources_count: number
  has_event_specific: boolean
}

export interface Step5Result {
  confirmed: number
  single_source: number
  unverified: number
  conflicted: number
}

export type StepResult = Step1Result | Step2Result | Step3Result | Step4Result | Step5Result | null

export interface StepState {
  status: StepStatus
  elapsedMs: number
  result: StepResult
  error: string | null
  fromCheckpoint: boolean
}

export interface Warning {
  step: number
  message: string
}

export interface GenerateRequest {
  sentence: string
  provider: Provider
  search_source: SearchSource
}
