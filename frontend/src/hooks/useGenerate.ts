import { useState, useRef, useCallback } from 'react'
import type { StepState, StepResult, Provider, SearchSource, Warning, BlockedState, TopicPageData } from '../types'

const STEP_COUNT = 6

function initialSteps(): StepState[] {
  return Array.from({ length: STEP_COUNT }, () => ({
    status: 'pending' as const,
    elapsedMs: 0,
    result: null,
    error: null,
    fromCheckpoint: false,
  }))
}

interface UseGenerateReturn {
  steps: StepState[]
  html: string | null
  outputTitle: string | null
  isGenerating: boolean
  error: string | null
  warnings: Warning[]
  blocked: BlockedState | null
  topicPage: TopicPageData | null
  hasOriginal: boolean
  runId: string | null
  generate: (sentence: string, provider: Provider, searchSource: SearchSource, runId?: string, fromStep?: number) => Promise<void>
  retryFromStep: (step: number) => void
  reset: () => void
  clearBlocked: () => void
  commitPageEdits: (edited: TopicPageData) => Promise<void>
  fetchOriginalPage: () => Promise<TopicPageData | null>
}

export function useGenerate(): UseGenerateReturn {
  const [steps, setSteps] = useState<StepState[]>(initialSteps())
  const [html, setHtml] = useState<string | null>(null)
  const [outputTitle, setOutputTitle] = useState<string | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<Warning[]>([])
  const [blocked, setBlocked] = useState<BlockedState | null>(null)
  const [topicPage, setTopicPage] = useState<TopicPageData | null>(null)
  const [hasOriginal, setHasOriginal] = useState(false)
  const [runId, setRunId] = useState<string | null>(null)

  const timersRef = useRef<Map<number, ReturnType<typeof setInterval>>>(new Map())
  const startTimesRef = useRef<Map<number, number>>(new Map())
  const abortRef = useRef<AbortController | null>(null)

  // Store current generate params for retry
  const lastParamsRef = useRef<{ sentence: string; provider: Provider; searchSource: SearchSource } | null>(null)

  const clearTimer = useCallback((stepIndex: number) => {
    const timer = timersRef.current.get(stepIndex)
    if (timer !== undefined) {
      clearInterval(timer)
      timersRef.current.delete(stepIndex)
    }
  }, [])

  const startTimer = useCallback((stepIndex: number) => {
    startTimesRef.current.set(stepIndex, Date.now())
    const timer = setInterval(() => {
      const start = startTimesRef.current.get(stepIndex)
      if (start === undefined) return
      setSteps(prev => {
        const next = [...prev]
        next[stepIndex] = { ...next[stepIndex], elapsedMs: Date.now() - start }
        return next
      })
    }, 100)
    timersRef.current.set(stepIndex, timer)
  }, [])

  const reset = useCallback(() => {
    if (abortRef.current) abortRef.current.abort()
    timersRef.current.forEach((_, idx) => clearTimer(idx))
    timersRef.current.clear()
    startTimesRef.current.clear()
    setSteps(initialSteps())
    setHtml(null)
    setOutputTitle(null)
    setIsGenerating(false)
    setError(null)
    setWarnings([])
    setBlocked(null)
    setTopicPage(null)
    setHasOriginal(false)
    setRunId(null)
    lastParamsRef.current = null
  }, [clearTimer])

  const clearBlocked = useCallback(() => setBlocked(null), [])

  const generate = useCallback(async (
    sentence: string,
    provider: Provider,
    searchSource: SearchSource,
    resumeRunId?: string,
    fromStep: number = 1,
  ) => {
    if (abortRef.current) abortRef.current.abort()

    // Clear timers for steps being re-run
    for (let i = fromStep - 1; i < STEP_COUNT; i++) clearTimer(i)
    timersRef.current.clear()
    startTimesRef.current.clear()

    // Reset only the steps being re-run; keep earlier steps as-is
    setSteps(prev => {
      if (fromStep <= 1) return initialSteps()
      const next = [...prev]
      for (let i = fromStep - 1; i < STEP_COUNT; i++) {
        next[i] = { status: 'pending', elapsedMs: 0, result: null, error: null, fromCheckpoint: false }
      }
      return next
    })

    if (fromStep <= 1) {
      setHtml(null)
      setOutputTitle(null)
      setWarnings([])
      setBlocked(null)
      setTopicPage(null)
      setHasOriginal(false)
      setRunId(null)
    }
    setError(null)
    setIsGenerating(true)
    lastParamsRef.current = { sentence, provider, searchSource }

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const response = await fetch('/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sentence,
          provider,
          search_source: searchSource,
          run_id: resumeRunId ?? null,
          from_step: fromStep,
        }),
        signal: controller.signal,
      })

      if (!response.ok) {
        throw new Error(`Server error ${response.status}: ${await response.text()}`)
      }
      if (!response.body) throw new Error('No response body received')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data:')) continue
          const jsonStr = trimmed.slice(5).trim()
          if (!jsonStr) continue

          let event: Record<string, unknown>
          try { event = JSON.parse(jsonStr) } catch { continue }

          // Init event carries the run_id
          if (event.type === 'init') {
            setRunId(event.run_id as string)
            continue
          }

          // Input gate stopped the pipeline before search — refusal or ambiguity.
          if (event.type === 'blocked') {
            setBlocked({
              verdict: event.verdict as BlockedState['verdict'],
              reason: (event.reason as string) ?? '',
              interpretations: (event.interpretations as string[]) ?? [],
            })
            setIsGenerating(false)
            continue
          }

          const stepNumber = event.step as number
          const status = event.status as string
          const stepIndex = stepNumber - 1

          if (status === 'warning') {
            setWarnings(prev => [...prev, { step: stepNumber, message: event.message as string }])
            continue
          }

          if (status === 'running') {
            startTimer(stepIndex)
            setSteps(prev => {
              const next = [...prev]
              next[stepIndex] = { ...next[stepIndex], status: 'running', elapsedMs: 0, fromCheckpoint: false }
              return next
            })
          } else if (status === 'done') {
            clearTimer(stepIndex)
            const finalElapsed = event.elapsed_ms as number
            const fromCheckpoint = (event.from_checkpoint as boolean) ?? false

            // Step 5 carries the full verified TopicPage — the editable source of truth.
            if (stepNumber === 5 && event.page) {
              setTopicPage(event.page as TopicPageData)
            }

            if (stepNumber === 6) {
              setHtml((event.html as string) ?? null)
              setOutputTitle((event.title as string) ?? null)
              setSteps(prev => {
                const next = [...prev]
                next[stepIndex] = { status: 'done', elapsedMs: finalElapsed, result: null, error: null, fromCheckpoint }
                return next
              })
              setIsGenerating(false)
            } else {
              setSteps(prev => {
                const next = [...prev]
                next[stepIndex] = {
                  status: 'done',
                  elapsedMs: finalElapsed,
                  result: (event.result as StepResult) ?? null,
                  error: null,
                  fromCheckpoint,
                }
                return next
              })
            }
          } else if (status === 'error') {
            clearTimer(stepIndex)
            const errMsg = (event.error as string) || 'Unknown error'
            setSteps(prev => {
              const next = [...prev]
              next[stepIndex] = {
                status: 'error',
                elapsedMs: event.elapsed_ms as number,
                result: null,
                error: errMsg,
                fromCheckpoint: false,
              }
              return next
            })
            setError(`Step ${stepNumber} failed: ${errMsg}`)
            setIsGenerating(false)
            return
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      const msg = err instanceof Error ? err.message : 'Failed to connect to backend'
      setError(msg)
      setIsGenerating(false)
    } finally {
      timersRef.current.forEach((_, idx) => clearTimer(idx))
    }
  }, [clearTimer, startTimer])

  const retryFromStep = useCallback((step: number) => {
    if (!lastParamsRef.current || !runId) return
    const { sentence, provider, searchSource } = lastParamsRef.current
    generate(sentence, provider, searchSource, runId, step)
  }, [runId, generate])

  // Persist edited structured data as the Step 5 checkpoint, then re-render (Step 6 only).
  const commitPageEdits = useCallback(async (edited: TopicPageData) => {
    if (!runId || !lastParamsRef.current) return
    const res = await fetch(`/run/${runId}/page`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(edited),
    })
    if (!res.ok) {
      setError(`Failed to save edits: ${res.status} ${await res.text()}`)
      return
    }
    const body = await res.json().catch(() => null)
    if (body?.has_original) setHasOriginal(true)
    setTopicPage(edited)
    const { sentence, provider, searchSource } = lastParamsRef.current
    await generate(sentence, provider, searchSource, runId, 6)
  }, [runId, generate])

  // Fetch the verifier's pre-edit output. Read-only — the caller loads it back into the
  // review form; the user still clicks Apply to commit + re-render.
  const fetchOriginalPage = useCallback(async (): Promise<TopicPageData | null> => {
    if (!runId) return null
    const res = await fetch(`/run/${runId}/page/original`)
    if (!res.ok) {
      setError(`Failed to load original: ${res.status} ${await res.text()}`)
      return null
    }
    return (await res.json()) as TopicPageData
  }, [runId])

  return { steps, html, outputTitle, isGenerating, error, warnings, blocked, topicPage, hasOriginal, runId, generate, retryFromStep, reset, clearBlocked, commitPageEdits, fetchOriginalPage }
}
