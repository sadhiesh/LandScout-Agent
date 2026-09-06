import { useEffect, useRef, useState } from 'react'
import MessageBubble from './MessageBubble'
import NarrationBubble from './NarrationBubble'
import ShortlistCard from '../results/ShortlistCard'
import CandidatePicker from './CandidatePicker'
import RefinementPicker, { type RefinementOption } from './RefinementPicker'
import ConfirmationActions from './ConfirmationActions'
import ModelPicker from '../lib/ModelPicker'
import { greeting, milestoneLead, memoryCallbackLead, errorLead } from './personalize'
import type { Message } from '../lib/useSession'
import type { TraceEvent } from '../lib/useTraceStream'
import type { Parcel } from '../results/ShortlistCard'
import { readSkipCachePreference, writeSkipCachePreference } from '../lib/cachePreference'
import styles from './ChatWindow.module.css'

const SUGGESTIONS = [
  '10–50 acres in Collin County under $500k',
  'Recreational land in McKinney with creek access',
  '20 acres near Frisco for future development',
  'Hunting property in Anna, 30–60 acres',
  'Farm land in Princeton, 40+ acres under $800k',
]

interface ChatWindowProps {
  userId: string | null
  sessionId: string | null
  messages: Message[]
  displayName: string | null
  onIdentify: (name: string) => Promise<{ returning: boolean; displayName: string; hydrated: boolean } | null>
  ensureSession: () => Promise<string | null>
  onAppendMessage: (message: Message) => void
  onReplaceMessages: (messages: Message[]) => void
  beginRun: () => string
  traceEvents: TraceEvent[]
  onViewAllParcels: () => void
  onSelectParcel: (parcel: Parcel) => void
  onRunStateChange: (isRunning: boolean) => void
}

export default function ChatWindow({
  userId,
  sessionId,
  messages,
  displayName,
  onIdentify,
  ensureSession,
  onAppendMessage,
  onReplaceMessages,
  beginRun,
  traceEvents,
  onViewAllParcels,
  onSelectParcel,
  onRunStateChange,
}: ChatWindowProps) {
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [currentRunId, setCurrentRunId] = useState<string | null>(null)
  const [skipCache, setSkipCache] = useState(readSkipCachePreference)
  const [llmProvider, setLlmProvider] = useState<string | null>(null)
  const [llmModel, setLlmModel] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }, [input])

  const handleToggleCache = (checked: boolean) => {
    setSkipCache(checked)
    writeSkipCachePreference(checked)
  }

  const handleModelSelection = (provider: string | null, model: string | null) => {
    setLlmProvider(provider)
    setLlmModel(model)
  }

  const send = async (
    raw: string,
    selectedParcelIds?: string[],
    selectedRefinementId?: string,
    selectedRefinementIds?: string[],
  ) => {
    const userMessage = raw.trim()
    if (!userMessage || isLoading) return
    setInput('')

    if (!userId) {
      setIsLoading(true)
      try {
        const result = await onIdentify(userMessage)
        if (!result) {
          onAppendMessage({
            message_id: Date.now(),
            role: 'assistant',
            content: 'Could not identify you. Please try again.',
            created_at: new Date().toISOString(),
          })
          return
        }
        if (!result.hydrated) {
          onAppendMessage({
            message_id: Date.now(),
            role: 'user',
            content: userMessage,
            created_at: new Date().toISOString(),
          })
          onAppendMessage({
            message_id: Date.now() + 1,
            role: 'assistant',
            content: greeting(result.displayName, result.returning),
            created_at: new Date().toISOString(),
          })
        }
      } finally {
        setIsLoading(false)
      }
      return
    }

    const activeSessionId = sessionId || (await ensureSession())
    if (!activeSessionId) {
      onAppendMessage({
        message_id: Date.now(),
        role: 'assistant',
        content: 'Could not create a session. Please try again.',
        created_at: new Date().toISOString(),
      })
      return
    }

    onAppendMessage({
      message_id: Date.now(),
      role: 'user',
      content: userMessage,
      created_at: new Date().toISOString(),
    })
    setIsLoading(true)
    onRunStateChange(true)
    const runId = beginRun()
    setCurrentRunId(runId)

    try {
      const body: any = {
        session_id: activeSessionId,
        message: userMessage,
        user_id: userId,
        skip_cache: skipCache,
        llm_provider: llmProvider,
        llm_model: llmModel,
      }
      
      // Include structured selections if provided.
      if (selectedParcelIds && selectedParcelIds.length > 0) {
        body.selected_parcel_ids = selectedParcelIds
      }
      if (selectedRefinementIds && selectedRefinementIds.length > 0) {
        body.selected_refinement_ids = selectedRefinementIds
      } else if (selectedRefinementId) {
        body.selected_refinement_id = selectedRefinementId
      }

      const response = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Run-ID': runId },
        body: JSON.stringify(body),
      })
      if (!response.ok) throw new Error(response.statusText)

      const messagesResponse = await fetch(`/sessions/${activeSessionId}/messages`)
      if (messagesResponse.ok) {
        const messagesData = (await messagesResponse.json()) as Message[]
        onReplaceMessages(messagesData)
      }
    } catch (error) {
      onAppendMessage({
        message_id: Date.now() + 1,
        role: 'assistant',
        content: `${errorLead(displayName)} (${error instanceof Error ? error.message : 'Unknown error'})`,
        created_at: new Date().toISOString(),
      })
    } finally {
      setIsLoading(false)
      setCurrentRunId(null)
      onRunStateChange(false)
    }
  }

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    void send(input)
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send(input)
    }
  }

  const title = userId ? (displayName ? `${displayName}'s land search` : 'Land search') : 'Welcome'
  const subtitle = userId
    ? 'Describe criteria in plain language — acreage, region, budget, and intended use.'
    : 'Start by telling the agent your name.'

  return (
    <div className={styles.panel}>
      <header className={styles.header}>
        <div>
          <div className={styles.title}>{title}</div>
          <div className={styles.subtitle}>{subtitle}</div>
        </div>
      </header>

      <div className={styles.messages}>
        {messages.length === 0 && (
          <div className={styles.welcome}>
            <div className={styles.welcomeMark}>LS</div>
            <h2>Find your next parcel</h2>
            <p>{userId ? 'Share acreage, location, budget, and intended use.' : 'What should we call you?'}</p>
          </div>
        )}

        {messages
          .filter((msg) => !msg.payload?.journey_step) // Collapse journey steps from display
          .map((msg) => {
            const parcels = msg.payload?.shortlist || []
            const candidates = msg.payload?.candidates || []
            const refinementOptions =
              msg.payload?.refinement_options ||
              msg.payload?.clarification?.refinement_options ||
              []
            const narrowingAnalysis = msg.payload?.narrowing_analysis
            const candidateLimit = msg.payload?.candidate_limit || 10
            const totalMatching = msg.payload?.total_matching || 0
            const hasResults = msg.role === 'assistant' && parcels.length > 0
            const hasCandidates = msg.role === 'assistant' && candidates.length > 0
            const hasRefinementOptions =
              msg.role === 'assistant' &&
              msg.payload?.clarification?.kind === 'facet_narrowing' &&
              refinementOptions.length > 0
            const awaitingConfirmation =
              msg.payload?.awaiting_clarification &&
              msg.payload?.clarification?.kind === 'criteria_confirmation'
            const lead = hasResults
              ? msg.payload?.cached
                ? memoryCallbackLead(displayName)
                : milestoneLead(displayName, parcels.length)
              : null

            return (
              <div key={msg.message_id}>
                <MessageBubble role={msg.role} content={msg.content} lead={lead} />

                {/* Criteria confirmation actions */}
                {awaitingConfirmation && (
                  <ConfirmationActions
                    onConfirm={async () => {
                      await send('yes')
                    }}
                    onEdit={() => {
                      setInput('Actually, ')
                      textareaRef.current?.focus()
                    }}
                    isLoading={isLoading}
                  />
                )}

                {hasRefinementOptions && (
                  <RefinementPicker
                    options={refinementOptions as RefinementOption[]}
                    totalMatching={totalMatching}
                    analysis={narrowingAnalysis}
                    onApply={async (selectedOptions) => {
                      const summary = selectedOptions
                        .map((option) => `${option.section}: ${option.label}`)
                        .join('; ')
                      await send(
                        `Apply ${summary}`,
                        undefined,
                        selectedOptions.length === 1 ? selectedOptions[0].id : undefined,
                        selectedOptions.length > 1 ? selectedOptions.map((option) => option.id) : undefined,
                      )
                    }}
                    isLoading={isLoading}
                  />
                )}

                {/* Candidate selection picker */}
                {hasCandidates && msg.payload?.clarification?.kind === 'candidate_selection' && (
                  <CandidatePicker
                    candidates={candidates}
                    limit={candidateLimit}
                    onAnalyze={async (selectedIds) => {
                      await send('Analyze these parcels', selectedIds)
                    }}
                    isLoading={isLoading}
                  />
                )}

                {/* Inline shortlist preview */}
                {hasResults && (
                  <div className={styles.inlineResults}>
                    <div className={styles.inlineParcels}>
                      {parcels.slice(0, 3).map((parcel: Parcel, idx: number) => (
                        <ShortlistCard
                          key={parcel.property_id || idx}
                          parcel={parcel}
                          rank={idx + 1}
                          variant="inline"
                          topPick={idx === 0}
                          onSelect={() => onSelectParcel(parcel)}
                        />
                      ))}
                    </div>
                    <button type="button" className={styles.viewAllBtn} onClick={onViewAllParcels}>
                      View all {parcels.length} results
                      {totalMatching ? ` of ${totalMatching} matches` : ''} <span aria-hidden>›</span>
                    </button>
                  </div>
                )}
              </div>
            )
          })}

        {isLoading && currentRunId && <NarrationBubble events={traceEvents} isComplete={false} />}
        <div ref={endRef} />
      </div>

      <div className={styles.composer}>
        {userId && (
          <div className={styles.controls}>
            <div className={styles.cacheToggle}>
              <label>
                <input 
                  type="checkbox" 
                  checked={skipCache} 
                  onChange={(e) => handleToggleCache(e.target.checked)}
                />
                <span>Skip saved results and run agents again</span>
              </label>
            </div>
            <ModelPicker onSelectionChange={handleModelSelection} />
          </div>
        )}
        {userId && messages.filter((m) => m.role === 'user').length < 3 && (
          <div className={styles.suggestions}>
            {SUGGESTIONS.map((s) => (
              <button key={s} type="button" className={styles.chip} onClick={() => void send(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
        <form className={styles.inputRow} onSubmit={onSubmit}>
          <textarea
            id="chat-composer"
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder={userId ? 'e.g. Looking for 20–50 acres near Austin under $300k for hunting…' : 'Enter your name…'}
            aria-label={userId ? 'Land search message' : 'Your name'}
            className={styles.textarea}
            disabled={isLoading}
          />
          <button type="submit" className={styles.sendBtn} disabled={isLoading || !input.trim()} aria-label="Send">
            ➤
          </button>
        </form>
      </div>
    </div>
  )
}
