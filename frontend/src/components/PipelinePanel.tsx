import { StepCard, STEP_NAMES } from './StepCard'
import type { StepState, Warning, BlockedState } from '../types'

interface PipelinePanelProps {
  steps: StepState[]
  warnings: Warning[]
  globalError: string | null
  blocked: BlockedState | null
  onUseInterpretation: (text: string) => void
  isGenerating: boolean
  onRetryFromStep: (step: number) => void
  hasRunId: boolean
}

export function PipelinePanel({
  steps,
  warnings,
  globalError,
  blocked,
  onUseInterpretation,
  isGenerating,
  onRetryFromStep,
  hasRunId,
}: PipelinePanelProps) {
  const step1Warnings = warnings.filter(w => w.step === 1)

  return (
    <section className="flex-1 min-w-0 flex flex-col bg-gray-50 overflow-y-auto">
      <div className="px-6 py-5 border-b border-gray-200 bg-white">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
          Pipeline Progress
        </h2>
      </div>

      <div className="px-6 py-5 flex flex-col gap-3">
        {globalError && (
          <div className="flex items-start gap-2 px-4 py-3 rounded-lg border border-red-200 bg-red-50 text-sm text-red-700">
            <span className="font-bold flex-shrink-0">✕</span>
            <span>{globalError}</span>
          </div>
        )}

        {blocked && <BlockedBanner blocked={blocked} onUseInterpretation={onUseInterpretation} />}

        {steps.map((step, i) => (
          <div key={i}>
            <StepCard
              stepNumber={i + 1}
              stepName={STEP_NAMES[i]}
              state={step}
              isGenerating={isGenerating}
              onRetry={hasRunId ? () => onRetryFromStep(i + 1) : undefined}
            />
            {i === 0 && step1Warnings.map((w, wi) => (
              <div
                key={wi}
                className="mt-2 flex items-start gap-2 px-3 py-2.5 rounded-md border border-amber-200 bg-amber-50 text-xs text-amber-800"
              >
                <span className="flex-shrink-0 mt-0.5">⚠</span>
                <span>{w.message}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  )
}

interface BlockedBannerProps {
  blocked: BlockedState
  onUseInterpretation: (text: string) => void
}

function BlockedBanner({ blocked, onUseInterpretation }: BlockedBannerProps) {
  const isRefused = blocked.verdict === 'refuse'
  const tone = isRefused
    ? 'border-red-200 bg-red-50 text-red-800'
    : 'border-amber-200 bg-amber-50 text-amber-900'

  return (
    <div className={`flex flex-col gap-3 px-4 py-4 rounded-lg border ${tone}`}>
      <div className="flex items-start gap-2">
        <span className="flex-shrink-0 mt-0.5">{isRefused ? '⛔' : '🤔'}</span>
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-semibold">
            {isRefused ? 'Can’t build a page for this input' : 'This could mean a few things'}
          </span>
          <span className="text-xs opacity-90">{blocked.reason}</span>
        </div>
      </div>

      {!isRefused && blocked.interpretations.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium opacity-70">Pick one to refine your description:</span>
          <div className="flex flex-col gap-1.5">
            {blocked.interpretations.map((interp, i) => (
              <button
                key={i}
                onClick={() => onUseInterpretation(interp)}
                className="text-left text-xs px-3 py-2 rounded-md border border-amber-300 bg-white/70 hover:bg-white hover:border-amber-400 transition-colors"
              >
                {interp}
              </button>
            ))}
          </div>
        </div>
      )}

      <span className="text-xs opacity-60">No search budget was spent — the input was caught before any web lookups.</span>
    </div>
  )
}
