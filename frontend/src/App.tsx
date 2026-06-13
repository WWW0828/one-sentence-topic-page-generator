import { useState } from 'react'
import { ConfigPanel } from './components/ConfigPanel'
import { PipelinePanel } from './components/PipelinePanel'
import { OutputPanel } from './components/OutputPanel'
import { useGenerate } from './hooks/useGenerate'
import type { Provider, SearchSource } from './types'

export default function App() {
  const [sentence, setSentence] = useState('')
  const [provider, setProvider] = useState<Provider>('gemini')
  const [searchSource, setSearchSource] = useState<SearchSource>('tavily')

  const { steps, html, outputTitle, isGenerating, error, warnings, blocked, topicPage, hasOriginal, runId, generate, retryFromStep, reset, clearBlocked, commitPageEdits, fetchOriginalPage } =
    useGenerate()

  const handleGenerate = () => {
    generate(sentence, provider, searchSource)
  }

  const handleUseInterpretation = (text: string) => {
    setSentence(text)
    clearBlocked()
  }

  // "New Page": clear pipeline state AND the event description input.
  const handleReset = () => {
    reset()
    setSentence('')
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50 font-sans">
      <ConfigPanel
        sentence={sentence}
        provider={provider}
        searchSource={searchSource}
        isGenerating={isGenerating}
        hasOutput={html !== null}
        onSentenceChange={setSentence}
        onProviderChange={setProvider}
        onSearchSourceChange={setSearchSource}
        onGenerate={handleGenerate}
        onReset={handleReset}
      />

      <PipelinePanel
        steps={steps}
        warnings={warnings}
        globalError={error}
        blocked={blocked}
        onUseInterpretation={handleUseInterpretation}
        isGenerating={isGenerating}
        onRetryFromStep={retryFromStep}
        hasRunId={runId !== null}
      />

      <OutputPanel
        html={html}
        title={outputTitle}
        topicPage={topicPage}
        hasOriginal={hasOriginal}
        isGenerating={isGenerating}
        onCommitEdits={commitPageEdits}
        onFetchOriginal={fetchOriginalPage}
      />
    </div>
  )
}
