/**
 * Action buttons for criteria confirmation messages.
 * Shows "Run search" and "Edit criteria" buttons when awaiting confirmation.
 */

import styles from './ConfirmationActions.module.css'

interface ConfirmationActionsProps {
  onConfirm: () => Promise<void>
  onEdit: () => void
  isLoading: boolean
}

export default function ConfirmationActions({
  onConfirm,
  onEdit,
  isLoading,
}: ConfirmationActionsProps) {
  return (
    <div className={styles.container}>
      <button
        className={styles.confirmButton}
        onClick={onConfirm}
        disabled={isLoading}
        aria-label="Run search with these criteria"
      >
        {isLoading ? 'Running...' : '✓ Run search'}
      </button>
      <button
        className={styles.editButton}
        onClick={onEdit}
        disabled={isLoading}
        aria-label="Edit search criteria"
      >
        ✎ Edit criteria
      </button>
    </div>
  )
}
