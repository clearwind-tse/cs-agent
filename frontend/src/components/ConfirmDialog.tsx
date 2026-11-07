import { useEffect } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import { cn } from '../utils'

interface ConfirmDialogProps {
  isOpen: boolean
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  variant?: 'default' | 'danger'
  onConfirm: () => void
  onCancel: () => void
}

export default function ConfirmDialog({
  isOpen,
  title,
  message,
  confirmText = '确定',
  cancelText = '取消',
  variant = 'default',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCancel()
      } else if (e.key === 'Enter') {
        onConfirm()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onConfirm, onCancel])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 bg-scrim/50 backdrop-blur-sm flex items-center justify-center z-[9998] p-4"
      onClick={onCancel}
    >
      <div
        className="bg-panel border border-panel-2 rounded-xl shadow-2xl w-full max-w-md animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between p-6 border-b border-panel-2">
          <div className="flex items-start gap-3">
            {variant === 'danger' && (
              <div className="w-10 h-10 rounded-full bg-bad/20 flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="w-5 h-5 text-bad" />
              </div>
            )}
            <div>
              <h3 className="text-lg font-semibold text-ink">{title}</h3>
            </div>
          </div>
          <button
            onClick={onCancel}
            className="p-1 hover:bg-line rounded-lg text-ink-muted hover:text-ink transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6">
          <p className="text-ink text-sm leading-relaxed">{message}</p>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-6 border-t border-panel-2">
          <button
            onClick={onCancel}
            className="px-4 py-2 bg-line hover:bg-line-strong text-ink rounded-lg transition-colors"
          >
            {cancelText}
          </button>
          <button
            onClick={onConfirm}
            className={cn(
              'px-4 py-2 text-ink rounded-lg transition-colors',
              variant === 'danger'
                ? 'bg-bad hover:bg-bad'
                : 'bg-iris hover:bg-flare'
            )}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
