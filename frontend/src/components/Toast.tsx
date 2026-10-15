// NOTE: 此文件使用纯组件，无需导入 React Hooks
import { X, CheckCircle, XCircle, Info, AlertTriangle } from 'lucide-react'
import { cn } from '../utils'
import { useToast, Toast as ToastType } from '../contexts/ToastContext'

interface ToastProps {
  toast: ToastType
}

const toastStyles = {
  success: {
    bg: 'bg-green-600',
    icon: CheckCircle,
    iconColor: 'text-white',
  },
  error: {
    bg: 'bg-red-600',
    icon: XCircle,
    iconColor: 'text-white',
  },
  info: {
    bg: 'bg-blue-600',
    icon: Info,
    iconColor: 'text-white',
  },
  warning: {
    bg: 'bg-yellow-600',
    icon: AlertTriangle,
    iconColor: 'text-white',
  },
}

function ToastItem({ toast }: ToastProps) {
  const { removeToast } = useToast()
  const style = toastStyles[toast.type]
  const Icon = style.icon

  return (
    <div
      className={cn(
        'flex items-start gap-3 p-4 rounded-lg shadow-xl max-w-sm w-full',
        'animate-slide-in-right',
        style.bg
      )}
    >
      <Icon className={cn('w-5 h-5 flex-shrink-0 mt-0.5', style.iconColor)} />
      <p className="flex-1 text-sm text-white font-medium">{toast.message}</p>
      <button
        onClick={() => removeToast(toast.id)}
        className="flex-shrink-0 text-white/80 hover:text-white transition-colors"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}

export default function ToastContainer() {
  const { toasts } = useToast()

  return (
    <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <ToastItem toast={toast} />
        </div>
      ))}
    </div>
  )
}
