import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import { useSession } from './lib/useSession'
import { useTraceStream } from './lib/useTraceStream'
import { usePanelLayout } from './lib/usePanelLayout'
import { useTheme } from './lib/ThemeContext'
import { readSkipCachePreference } from './lib/cachePreference'
import SessionSidebar from './sessions/SessionSidebar'
import ChatWindow from './chat/ChatWindow'
import InspectorOverlay from './inspector/InspectorOverlay'
import ShowcaseMode from './showcase/ShowcaseMode'
import IconRail from './navigation/IconRail'
import LandScoutLogo from './branding/LandScoutLogo'
import RightWorkspace, { type WorkspaceTab } from './workspace/RightWorkspace'
import type { Message } from './lib/useSession'
import type { Parcel } from './results/ShortlistCard'
import styles from './App.module.css'

const SAMPLE_QUERY = '10–50 acres in Collin County under $500k for recreational use'

export default function App() {
  const session = useSession()
  const trace = useTraceStream()
  const layout = usePanelLayout()
  const { suggestTheme, restoreSuggested } = useTheme()

  const [showcaseMode, setShowcaseMode] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [sampleRunning, setSampleRunning] = useState(false)
  const [chatRunActive, setChatRunActive] = useState(false)
  const [activeWorkspaceTab, setActiveWorkspaceTab] = useState<WorkspaceTab>('observability')
  const [selectedParcel, setSelectedParcel] = useState<Parcel | null>(null)
  const [mobilePane, setMobilePane] = useState<'chat' | 'workspace'>('chat')

  const latestAssistant = [...session.messages].reverse().find((m) => m.role === 'assistant' && m.payload?.shortlist)
  const parcels = latestAssistant?.payload?.shortlist ?? []
  const totalMatching = latestAssistant?.payload?.total_matching ?? 0
  const resultsIdentity = `${session.sessionId ?? ''}:${latestAssistant?.message_id ?? ''}`

  useEffect(() => {
    setSelectedParcel(null)
  }, [resultsIdentity])

  useEffect(() => {
    if (inspectorOpen) {
      const onKey = (e: KeyboardEvent) => {
        if (e.key === 'Escape') setInspectorOpen(false)
      }
      window.addEventListener('keydown', onKey)
      return () => window.removeEventListener('keydown', onKey)
    }
  }, [inspectorOpen])

  const enterShowcase = useCallback(() => {
    suggestTheme('command')
    setShowcaseMode(true)
  }, [suggestTheme])

  const exitShowcase = useCallback(() => {
    restoreSuggested()
    setShowcaseMode(false)
  }, [restoreSuggested])

  const runSample = useCallback(async () => {
    if (!session.userId || sampleRunning) return
    setSampleRunning(true)
    const activeSessionId = session.sessionId || (await session.ensureSession())
    if (!activeSessionId) {
      setSampleRunning(false)
      return
    }
    const userMsg: Message = {
      message_id: Date.now(),
      role: 'user',
      content: SAMPLE_QUERY,
      created_at: new Date().toISOString(),
    }
    session.appendMessage(userMsg)
    const runId = trace.beginRun()
    try {
      const response = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Run-ID': runId },
        body: JSON.stringify({
          session_id: activeSessionId,
          message: SAMPLE_QUERY,
          user_id: session.userId,
          skip_cache: readSkipCachePreference(),
        }),
      })
      if (!response.ok) throw new Error(response.statusText)
      const messagesResponse = await fetch(`/sessions/${activeSessionId}/messages`)
      if (messagesResponse.ok) {
        const messagesData = (await messagesResponse.json()) as Message[]
        const existingIds = new Set(session.messages.map((m) => m.message_id))
        messagesData.filter((m) => !existingIds.has(m.message_id)).forEach((m) => session.appendMessage(m))
      }
    } catch {
      // Surfaced already via the chat pane's own error handling on next real turn.
    } finally {
      setSampleRunning(false)
    }
  }, [session, sampleRunning, trace])

  const openParcelList = useCallback(() => {
    setSelectedParcel(null)
    setActiveWorkspaceTab('parcels')
    setMobilePane('workspace')
  }, [])

  const openParcel = useCallback((parcel: Parcel) => {
    setSelectedParcel(parcel)
    setActiveWorkspaceTab('parcels')
    setMobilePane('workspace')
  }, [])

  const createSearch = useCallback(async () => {
    trace.resetStream()
    setChatRunActive(false)
    setSelectedParcel(null)
    setMobilePane('chat')
    await session.createSession()
  }, [session, trace])

  const switchSession = useCallback(async (sessionId: string) => {
    trace.resetStream()
    setChatRunActive(false)
    setSelectedParcel(null)
    setMobilePane('chat')
    await session.switchSession(sessionId)
  }, [session, trace])

  const [sessionsCol, chatCol, workspaceCol] = layout.columnTemplates
  const layoutStyle = {
    '--sessions-track': sessionsCol,
    '--chat-track': chatCol,
    '--workspace-track': workspaceCol,
  } as CSSProperties

  if (showcaseMode) {
    return (
      <div className={styles.app}>
        <ShowcaseMode events={trace.panels.trace} isRunning={sampleRunning} onRunSample={() => void runSample()} onExit={exitShowcase} />
      </div>
    )
  }

  return (
    <div className={styles.app}>
      <IconRail
        sessionsOpen={!layout.sessionsCollapsed}
        onNewSearch={() => void createSearch()}
        onOpenChat={() => {
          setMobilePane('chat')
          window.requestAnimationFrame(() => document.getElementById('chat-composer')?.focus())
        }}
        onToggleSessions={layout.toggleSessions}
        onOpenInspector={() => setInspectorOpen(true)}
        onOpenShowcase={enterShowcase}
      />
      <main className={styles.main}>
        <header className={styles.mobileNav} aria-label="Mobile workspace navigation">
          <div className={styles.mobileBrand}>
            <LandScoutLogo />
          </div>
          <div className={styles.mobileTabs} role="group" aria-label="Choose mobile pane">
            <button
              type="button"
              aria-pressed={mobilePane === 'chat'}
              className={mobilePane === 'chat' ? styles.mobileActive : ''}
              onClick={() => setMobilePane('chat')}
            >
              Chat
            </button>
            <button
              type="button"
              aria-pressed={mobilePane === 'workspace'}
              className={mobilePane === 'workspace' ? styles.mobileActive : ''}
              onClick={() => setMobilePane('workspace')}
            >
              Workspace
            </button>
          </div>
        </header>
        <div className={styles.body} ref={layout.containerRef} style={layoutStyle}>
          {!layout.sessionsCollapsed && (
            <>
              <div className={styles.sessionsPane}>
                <SessionSidebar
                  sessions={session.sessions}
                  currentSessionId={session.sessionId}
                  onNewSession={() => void createSearch()}
                  onSelectSession={(sid) => void switchSession(sid)}
                  onSwitchUser={session.switchUser}
                  displayName={session.displayName}
                  collapsed={false}
                  onToggleCollapse={layout.toggleSessions}
                />
              </div>
              <button type="button" className={styles.sessionScrim} aria-label="Close sessions" onClick={layout.toggleSessions} />
            </>
          )}
          <div className={styles.handle} onMouseDown={layout.onHandleMouseDown} aria-hidden />

          <section className={styles.chatPane} data-mobile-hidden={mobilePane !== 'chat'}>
            <ChatWindow
              userId={session.userId}
              sessionId={session.sessionId}
              messages={session.messages}
              displayName={session.displayName}
              onIdentify={session.identifyUser}
              ensureSession={session.ensureSession}
              onAppendMessage={session.appendMessage}
              onReplaceMessages={session.setMessages}
              beginRun={trace.beginRun}
              traceEvents={trace.panels.trace}
              onViewAllParcels={openParcelList}
              onSelectParcel={openParcel}
              onRunStateChange={setChatRunActive}
            />
          </section>
          <section className={styles.rightPane} data-mobile-hidden={mobilePane !== 'workspace'}>
            <RightWorkspace
              activeTab={activeWorkspaceTab}
              onTabChange={setActiveWorkspaceTab}
              events={trace.panels.trace}
              parcels={parcels}
              totalMatching={totalMatching}
              isRunActive={chatRunActive || sampleRunning}
              selectedParcel={selectedParcel}
              onSelectParcel={openParcel}
              onBackToResults={() => setSelectedParcel(null)}
              onOpenInspector={() => setInspectorOpen(true)}
            />
          </section>
        </div>
      </main>

      {inspectorOpen && <InspectorOverlay panels={trace.panels} onClose={() => setInspectorOpen(false)} />}
    </div>
  )
}
