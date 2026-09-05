import styles from './MessageBubble.module.css'

interface MessageBubbleProps {
  role: 'user' | 'assistant'
  content: string
  /** Small conversational lead-in line above the bubble (milestone/memory-callback framing). */
  lead?: string | null
}

export default function MessageBubble({ role, content, lead }: MessageBubbleProps) {
  const isUser = role === 'user'
  return (
    <div className={isUser ? `${styles.msg} ${styles.user}` : styles.msg}>
      <div className={styles.avatar} aria-hidden>
        {isUser ? 'You' : 'LS'}
      </div>
      <div className={styles.wrap}>
        {lead && <div className={styles.lead}>{lead}</div>}
        <div className={styles.bubble}>{content}</div>
      </div>
    </div>
  )
}
