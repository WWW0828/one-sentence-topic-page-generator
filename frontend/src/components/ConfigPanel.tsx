import type { Provider, SearchSource } from '../types'

interface ConfigPanelProps {
  sentence: string
  provider: Provider
  searchSource: SearchSource
  isGenerating: boolean
  hasOutput: boolean
  onSentenceChange: (v: string) => void
  onProviderChange: (v: Provider) => void
  onSearchSourceChange: (v: SearchSource) => void
  onGenerate: () => void
  onReset: () => void
}

const MAX_CHARS = 280
const MIN_CHARS = 20

export function ConfigPanel({
  sentence,
  provider,
  searchSource,
  isGenerating,
  hasOutput,
  onSentenceChange,
  onProviderChange,
  onSearchSourceChange,
  onGenerate,
  onReset,
}: ConfigPanelProps) {
  const charCount = sentence.length
  const canGenerate = charCount >= MIN_CHARS && !isGenerating

  return (
    <aside className="w-[280px] flex-shrink-0 flex flex-col bg-white border-r border-gray-200 overflow-y-auto">
      <div className="px-6 py-5 border-b border-gray-100">
        <h1 className="text-base font-semibold text-gray-900 tracking-tight leading-tight">
          Topic Page Generator
        </h1>
        <p className="text-xs text-gray-400 mt-0.5">Editorial automation tool</p>
      </div>

      <div className="px-6 py-5 flex flex-col gap-5 flex-1">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-gray-700 uppercase tracking-wide">
            Event Description
          </label>
          <textarea
            className="w-full text-sm text-gray-900 placeholder-gray-400 border border-gray-200 rounded-md px-3 py-2.5 resize-none focus:outline-none focus:ring-2 focus:ring-blue-800 focus:border-transparent transition-shadow"
            rows={4}
            maxLength={MAX_CHARS}
            placeholder="Describe the event in one sentence..."
            value={sentence}
            onChange={e => onSentenceChange(e.target.value)}
            disabled={isGenerating}
          />
          <div className="flex justify-end">
            <span className={`text-xs tabular-nums ${charCount > MAX_CHARS * 0.9 ? 'text-amber-600' : 'text-gray-400'}`}>
              {charCount} / {MAX_CHARS}
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <label className="text-xs font-medium text-gray-700 uppercase tracking-wide">
            LLM Provider
          </label>
          <RadioGroup
            name="provider"
            value={provider}
            onChange={v => onProviderChange(v as Provider)}
            disabled={isGenerating}
            options={[
              { value: 'gemini', label: 'Gemini' },
              { value: 'claude', label: 'Claude' },
            ]}
          />
        </div>

        <div className="flex flex-col gap-2">
          <label className="text-xs font-medium text-gray-700 uppercase tracking-wide">
            Web Search
          </label>
          <RadioGroup
            name="search_source"
            value={searchSource}
            onChange={v => onSearchSourceChange(v as SearchSource)}
            disabled={isGenerating}
            options={[
              { value: 'tavily', label: 'Tavily' },
            ]}
          />
        </div>

        <div className="flex flex-col gap-2 mt-auto pt-2">
          <button
            onClick={onGenerate}
            disabled={!canGenerate}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-md text-sm font-medium text-white bg-blue-800 hover:bg-blue-900 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {isGenerating ? (
              <>
                <Spinner />
                Generating...
              </>
            ) : (
              'Generate'
            )}
          </button>

          {hasOutput && !isGenerating && (
            <button
              onClick={onReset}
              className="w-full px-4 py-2.5 rounded-md text-sm font-medium text-gray-600 border border-gray-200 hover:bg-gray-50 transition-colors"
            >
              New Page
            </button>
          )}
        </div>
      </div>
    </aside>
  )
}

interface RadioGroupProps {
  name: string
  value: string
  options: { value: string; label: string }[]
  disabled: boolean
  onChange: (v: string) => void
}

function RadioGroup({ name, value, options, disabled, onChange }: RadioGroupProps) {
  return (
    <div className="flex flex-col gap-1.5">
      {options.map(opt => (
        <label
          key={opt.value}
          className={`flex items-center gap-2.5 px-3 py-2 rounded-md border cursor-pointer transition-colors ${
            value === opt.value
              ? 'border-blue-800 bg-blue-50 text-blue-900'
              : 'border-gray-200 text-gray-700 hover:bg-gray-50'
          } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          <input
            type="radio"
            name={name}
            value={opt.value}
            checked={value === opt.value}
            onChange={() => onChange(opt.value)}
            disabled={disabled}
            className="sr-only"
          />
          <span
            className={`w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
              value === opt.value ? 'border-blue-800' : 'border-gray-300'
            }`}
          >
            {value === opt.value && (
              <span className="w-1.5 h-1.5 rounded-full bg-blue-800 block" />
            )}
          </span>
          <span className="text-sm">{opt.label}</span>
        </label>
      ))}
    </div>
  )
}

function Spinner() {
  return (
    <svg
      className="animate-spin h-4 w-4 text-white"
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
