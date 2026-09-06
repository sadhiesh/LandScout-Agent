/**
 * Session management hook — owns user identity, session list, and history.
 * Same /users and /sessions contract as the existing console (see ui/CLAUDE.md).
 */

import { useState, useEffect, useCallback } from 'react'

export interface User {
  user_id: string
  display_name: string
}

export interface Session {
  session_id: string
  title: string | null
  created_at: string
  last_seen_at: string
  run_count: number
}

export interface Message {
  message_id: number
  role: 'user' | 'assistant'
  content: string
  payload?: {
    shortlist?: any[]
    candidates?: any[]  // Legacy parcel-selection payloads
    candidate_analysis?: Record<string, any>
    refinement_options?: Array<{
      id: string
      section: string
      label: string
      count: number
      criteria_patch?: Record<string, any>
      clear_fields?: string[]
      tier?: 'primary' | 'secondary'
    }>
    narrowing_analysis?: {
      common_conditions?: string[]
      recommendations?: string[]
    }
    candidate_limit?: number
    awaiting_clarification?: boolean
    clarification?: {
      kind?: string
      pending_criteria?: Record<string, any>
      pending_provenance?: Record<string, string>
      refinement_options?: Array<{
        id: string
        section: string
        label: string
        count: number
        tier?: 'primary' | 'secondary'
      }>
      run_id?: string
    }
    error?: string  // Scout/tool error that should skip this turn
    total_matching?: number
    cached?: boolean
    journey_step?: boolean
    step_type?: string
    step_details?: Record<string, any>
    criteria?: Record<string, any>
    criteria_provenance?: Record<string, string>
    journey?: Array<{
      kind: string
      summary: string
      timestamp: string
      agent?: string
      data?: Record<string, any>
    }>
  }
  created_at: string
}

export function useSession() {
  const [userId, setUserId] = useState<string | null>(null)
  const [displayName, setDisplayName] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const storedUserId = localStorage.getItem('landscout_next_user_id')
    const storedSessionId = localStorage.getItem('landscout_next_session_id')

    if (storedUserId) {
      setUserId(storedUserId)
      fetch(`/users/${storedUserId}`)
        .then((res) => res.json())
        .then((data) => {
          setDisplayName(data.display_name)
          loadUserSessions(storedUserId)
        })
        .catch((err) => {
          console.error('Failed to load user:', err)
          localStorage.removeItem('landscout_next_user_id')
          setUserId(null)
        })
    }

    if (storedSessionId) {
      setSessionId(storedSessionId)
      loadSessionMessages(storedSessionId)
    }
  }, [])

  const loadUserSessions = async (uid: string): Promise<Session[]> => {
    try {
      const res = await fetch(`/users/${uid}/sessions`)
      const data = await res.json()
      setSessions(data)
      return data as Session[]
    } catch (err) {
      console.error('Failed to load sessions:', err)
      return []
    }
  }

  const loadSessionMessages = async (sid: string) => {
    try {
      const res = await fetch(`/sessions/${sid}/messages`)
      const data = await res.json()
      setMessages(data)
    } catch (err) {
      console.error('Failed to load messages:', err)
      setMessages([])
    }
  }

  const createSessionForUser = async (uid: string): Promise<string | null> => {
    try {
      const res = await fetch('/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: uid }),
      })
      if (!res.ok) throw new Error('Failed to create session')
      const data = await res.json()
      const newSessionId = data.session_id as string

      setSessionId(newSessionId)
      localStorage.setItem('landscout_next_session_id', newSessionId)
      setMessages([])
      await loadUserSessions(uid)
      return newSessionId
    } catch (err) {
      console.error('Failed to create session:', err)
      return null
    }
  }

  const identifyUser = useCallback(
    async (name: string): Promise<{ returning: boolean; displayName: string; hydrated: boolean } | null> => {
      setLoading(true)
      try {
        const res = await fetch('/users/identify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        })
        if (!res.ok) throw new Error('Identification failed')
        const data = await res.json()

        setUserId(data.user_id)
        setDisplayName(data.display_name)
        localStorage.setItem('landscout_next_user_id', data.user_id)

        const existingSessions = await loadUserSessions(data.user_id)
        const storedSessionId = localStorage.getItem('landscout_next_session_id')
        let hydrated = false

        if (storedSessionId) {
          setSessionId(storedSessionId)
          await loadSessionMessages(storedSessionId)
          hydrated = true
        } else if (existingSessions.length > 0) {
          const latest = existingSessions[0]
          setSessionId(latest.session_id)
          localStorage.setItem('landscout_next_session_id', latest.session_id)
          await loadSessionMessages(latest.session_id)
          hydrated = true
        } else {
          await createSessionForUser(data.user_id)
        }

        return {
          returning: Boolean(data.returning),
          displayName: data.display_name as string,
          hydrated,
        }
      } catch (err) {
        console.error('Failed to identify user:', err)
        return null
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  const createSession = useCallback(async (): Promise<string | null> => {
    if (!userId) return null
    return createSessionForUser(userId)
  }, [userId])

  const ensureSession = useCallback(async (): Promise<string | null> => {
    const existing = sessionId || localStorage.getItem('landscout_next_session_id')
    if (existing) {
      if (!sessionId) setSessionId(existing)
      return existing
    }
    if (!userId) return null
    return createSessionForUser(userId)
  }, [sessionId, userId])

  const switchSession = useCallback(async (sid: string) => {
    setSessionId(sid)
    localStorage.setItem('landscout_next_session_id', sid)
    await loadSessionMessages(sid)
  }, [])

  const switchUser = useCallback(() => {
    localStorage.removeItem('landscout_next_user_id')
    localStorage.removeItem('landscout_next_session_id')
    setUserId(null)
    setDisplayName(null)
    setSessionId(null)
    setSessions([])
    setMessages([])
  }, [])

  const appendMessage = useCallback((message: Message) => {
    setMessages((prev) => [...prev, message])
  }, [])

  return {
    userId,
    displayName,
    sessionId,
    sessions,
    messages,
    loading,
    identifyUser,
    createSession,
    ensureSession,
    switchSession,
    switchUser,
    loadUserSessions,
    appendMessage,
    setMessages,
  }
}
