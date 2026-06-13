import { useState } from 'react'
import { ReviewPanel } from './ReviewPanel'
import type { TopicPageData } from '../types'

interface OutputPanelProps {
  html: string | null
  title: string | null
  topicPage: TopicPageData | null
  hasOriginal: boolean
  isGenerating: boolean
  onCommitEdits: (edited: TopicPageData) => void
  onFetchOriginal: () => Promise<TopicPageData | null>
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .trim()
}

export function OutputPanel({ html, title, topicPage, hasOriginal, isGenerating, onCommitEdits, onFetchOriginal }: OutputPanelProps) {
  const [tab, setTab] = useState<'preview' | 'review'>('preview')

  const handleDownload = () => {
    if (!html) return
    const blob = new Blob([html], { type: 'text/html' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${slugify(title ?? 'topic-page')}.html`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleOpenInTab = () => {
    if (!html) return
    const blob = new Blob([html], { type: 'text/html' })
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank')
  }

  return (
    <section className="w-[40%] flex-shrink-0 flex flex-col bg-white border-l border-gray-200 overflow-y-auto">
      <div className="px-6 py-5 border-b border-gray-200 flex items-center justify-between gap-3 min-h-[57px]">
        {html ? (
          <div className="flex items-center gap-1 bg-gray-100 rounded-md p-0.5">
            <TabButton active={tab === 'preview'} onClick={() => setTab('preview')}>Preview</TabButton>
            <TabButton active={tab === 'review'} onClick={() => setTab('review')} disabled={!topicPage}>
              Review &amp; edit
            </TabButton>
          </div>
        ) : (
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Output</h2>
        )}
        {html && tab === 'preview' && (
          <button
            onClick={handleDownload}
            className="flex items-center gap-1.5 text-xs font-medium text-blue-800 border border-blue-200 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md transition-colors"
          >
            <DownloadIcon />
            Download .html
          </button>
        )}
      </div>

      <div className="flex-1 flex flex-col p-6">
        {!html ? (
          <EmptyState />
        ) : tab === 'review' && topicPage ? (
          <ReviewPanel
            page={topicPage}
            hasOriginal={hasOriginal}
            isGenerating={isGenerating}
            onCommitEdits={onCommitEdits}
            onFetchOriginal={onFetchOriginal}
          />
        ) : (
          <div className="flex flex-col gap-3 flex-1">
            {title && (
              <p className="text-sm font-medium text-gray-700 truncate" title={title}>
                {title}
              </p>
            )}
            <iframe
              srcDoc={html}
              sandbox="allow-same-origin"
              className="w-full flex-1 border border-gray-200 rounded-md"
              style={{ minHeight: '500px' }}
              title="Generated topic page preview"
            />
            <button
              onClick={handleOpenInTab}
              className="self-start text-xs text-blue-700 hover:text-blue-900 hover:underline transition-colors"
            >
              Open in new tab ↗
            </button>
          </div>
        )}
      </div>
    </section>
  )
}

function TabButton({ active, onClick, disabled, children }: { active: boolean; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`text-xs font-medium px-3 py-1.5 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
        active ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
      }`}
    >
      {children}
    </button>
  )
}

function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center border-2 border-dashed border-gray-200 rounded-lg text-center px-8 py-12">
      <div className="w-12 h-12 rounded-full bg-gray-100 flex items-center justify-center mb-4">
        <PageIcon />
      </div>
      <p className="text-sm font-medium text-gray-500">Generated page will appear here</p>
      <p className="text-xs text-gray-400 mt-1">
        Fill in the event description and click Generate
      </p>
    </div>
  )
}

function DownloadIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      className="h-3.5 w-3.5"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
    </svg>
  )
}

function PageIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      className="h-6 w-6 text-gray-300"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
    </svg>
  )
}
