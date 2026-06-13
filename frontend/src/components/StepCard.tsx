import type { StepState, Step1Result, Step2Result, Step3Result, Step4Result, Step5Result } from '../types'

interface StepCardProps {
  stepNumber: number
  stepName: string
  state: StepState
  onRetry?: () => void
  isGenerating: boolean
}

const STEP_NAMES = [
  'Event Classification',
  'Search Query Generation',
  'Web Search',
  'Data Extraction',
  'Source Verification',
  'Render HTML',
]

export function StepCard({ stepNumber, stepName, state, onRetry, isGenerating }: StepCardProps) {
  const { status, elapsedMs, result, error, fromCheckpoint } = state
  const isExpanded = status === 'running' || status === 'done' || status === 'error'

  return (
    <div
      className={`rounded-lg border bg-white shadow-sm transition-all duration-200 ${
        status === 'running'
          ? 'border-blue-400 shadow-blue-100'
          : status === 'done'
          ? 'border-green-200'
          : status === 'error'
          ? 'border-red-300'
          : 'border-gray-200'
      }`}
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <StatusIcon status={status} />
        <span
          className={`text-sm font-medium flex-1 ${
            status === 'pending' ? 'text-gray-400' : 'text-gray-800'
          }`}
        >
          {stepNumber}. {stepName}
        </span>
        {fromCheckpoint && (
          <span className="text-xs text-amber-600 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded font-medium">
            cached
          </span>
        )}
        {!fromCheckpoint && (status === 'running' || status === 'done' || status === 'error') && (
          <span className="text-xs tabular-nums text-gray-400">
            {formatElapsed(elapsedMs)}
          </span>
        )}
      </div>

      {isExpanded && (
        <div className="px-4 pb-4 pt-0">
          <div className="border-t border-gray-100 pt-3">
            {status === 'running' && (
              <p className="text-xs text-blue-600 animate-pulse">Processing…</p>
            )}
            {status === 'error' && (
              <div className="flex flex-col gap-2">
                <p className="text-xs text-red-600">{error}</p>
                {onRetry && (
                  <button
                    onClick={onRetry}
                    className="self-start flex items-center gap-1.5 text-xs font-medium text-white bg-red-500 hover:bg-red-600 px-2.5 py-1.5 rounded transition-colors"
                  >
                    ↺ Retry from step {stepNumber}
                  </button>
                )}
              </div>
            )}
            {status === 'done' && result !== null && (
              <StepResult stepNumber={stepNumber} result={result} />
            )}
            {status === 'done' && stepNumber === 6 && (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-green-700 bg-green-50 px-2.5 py-1 rounded-full">
                <span>✓</span> Ready
              </span>
            )}
            {status === 'done' && onRetry && !isGenerating && (
              <button
                onClick={onRetry}
                className="mt-2 self-start flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
              >
                ↺ Re-run from here
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export { STEP_NAMES }

interface StepResultProps {
  stepNumber: number
  result: NonNullable<StepState['result']>
}

function StepResult({ stepNumber, result }: StepResultProps) {
  if (stepNumber === 1) {
    const r = result as Step1Result
    return (
      <div className="flex flex-col gap-2.5">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-block px-2 py-0.5 rounded text-xs font-semibold bg-blue-100 text-blue-800 uppercase tracking-wide">
            {r.event_type}
          </span>
          <span className="text-sm text-gray-700 font-medium">{r.suggested_title}</span>
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-500">Confidence</span>
            <span className="text-xs font-medium text-gray-700 tabular-nums">
              {Math.round(r.confidence * 100)}%
            </span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-1.5">
            <div
              className="h-1.5 rounded-full bg-blue-500 transition-all duration-500"
              style={{ width: `${Math.round(r.confidence * 100)}%` }}
            />
          </div>
        </div>
        {r.entities && r.entities.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {r.entities.map((entity, i) => (
              <span
                key={i}
                className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded"
              >
                {entity}
              </span>
            ))}
          </div>
        )}
      </div>
    )
  }

  if (stepNumber === 2) {
    const r = result as Step2Result
    return (
      <div className="flex flex-wrap gap-1.5">
        {r.queries.map((q, i) => (
          <span
            key={i}
            className="text-xs bg-blue-50 text-blue-700 border border-blue-100 px-2.5 py-1 rounded-full"
          >
            {q}
          </span>
        ))}
      </div>
    )
  }

  if (stepNumber === 3) {
    const r = result as Step3Result
    return (
      <div className="flex flex-col gap-2">
        <p className="text-xs font-medium text-gray-700">
          {r.source_count} source{r.source_count !== 1 ? 's' : ''} found
        </p>
        <ul className="flex flex-col gap-1.5">
          {r.sources.slice(0, 5).map((src, i) => (
            <li key={i} className="flex flex-col">
              <span className="text-xs text-gray-700 font-medium leading-snug line-clamp-1">
                {src.title}
              </span>
              <span className="text-xs text-gray-400">{src.publisher}</span>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  if (stepNumber === 4) {
    const r = result as Step4Result
    return (
      <div className="flex flex-wrap gap-x-4 gap-y-1.5">
        <StatChip label="facts" value={r.key_facts_count} />
        <StatChip label="timeline" value={r.timeline_count} />
        <StatChip label="entities" value={r.entities_count} />
        <StatChip label="sources" value={r.sources_count} />
        <span className={`text-xs font-medium ${r.has_event_specific ? 'text-green-600' : 'text-gray-400'}`}>
          event-specific: {r.has_event_specific ? 'yes' : 'no'}
        </span>
      </div>
    )
  }

  if (stepNumber === 5) {
    const r = result as Step5Result
    const graded = r.confirmed + r.single_source + r.unverified + r.conflicted
    const supported = r.confirmed + r.single_source
    return (
      <div className="flex flex-col gap-2">
        <p className="text-xs text-gray-600">
          <span className="font-semibold text-gray-800">{supported}/{graded}</span> claims traced to a source
        </p>
        <div className="flex flex-wrap gap-1.5">
          <VerifyChip label="confirmed" value={r.confirmed} className="bg-green-50 text-green-700 border-green-200" />
          <VerifyChip label="1 source" value={r.single_source} className="bg-gray-50 text-gray-600 border-gray-200" />
          <VerifyChip label="conflicted" value={r.conflicted} className="bg-amber-50 text-amber-700 border-amber-200" />
          <VerifyChip label="unverified" value={r.unverified} className="bg-red-50 text-red-600 border-red-200" />
        </div>
      </div>
    )
  }

  return null
}

function VerifyChip({ label, value, className }: { label: string; value: number; className: string }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${className}`}>
      {value} {label}
    </span>
  )
}

function StatChip({ label, value }: { label: string; value: number }) {
  return (
    <span className="text-xs text-gray-600">
      <span className="font-semibold text-gray-800">{value}</span> {label}
    </span>
  )
}

function StatusIcon({ status }: { status: StepState['status'] }) {
  if (status === 'pending') {
    return (
      <span className="w-5 h-5 rounded-full border-2 border-gray-200 flex-shrink-0" />
    )
  }
  if (status === 'running') {
    return (
      <svg
        className="animate-spin h-5 w-5 text-blue-600 flex-shrink-0"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle
          className="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
        />
      </svg>
    )
  }
  if (status === 'done') {
    return (
      <span className="w-5 h-5 rounded-full bg-green-500 flex items-center justify-center flex-shrink-0">
        <span className="text-white text-xs leading-none font-bold">✓</span>
      </span>
    )
  }
  return (
    <span className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center flex-shrink-0">
      <span className="text-white text-xs leading-none font-bold">✕</span>
    </span>
  )
}

function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
