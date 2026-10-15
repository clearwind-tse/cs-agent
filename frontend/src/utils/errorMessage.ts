export function getErrorMessage(error: unknown, fallback: string): string {
  const err = error as any
  const detail = err?.response?.data?.detail

  if (typeof detail === 'string' && detail.trim()) return detail

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item: any) => (typeof item?.msg === 'string' ? item.msg : ''))
      .filter(Boolean)
    if (messages.length > 0) return messages.join('；')
  }

  if (detail && typeof detail === 'object' && typeof detail.msg === 'string' && detail.msg.trim()) {
    return detail.msg
  }

  if (typeof err?.message === 'string' && err.message.trim()) return err.message

  return fallback
}
