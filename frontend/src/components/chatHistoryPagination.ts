export function getHistoryRequestPage(params: {
  currentPage: number
  reset: boolean
}) {
  const { currentPage, reset } = params
  const nextPage = reset ? 1 : currentPage + 1
  return {
    pageToLoad: nextPage,
    nextPage,
  }
}

export function prependUniqueMessages<T extends { id: number }>(
  existingMessages: T[],
  olderMessages: T[],
) {
  const seenIds = new Set<number>()
  const merged: T[] = []

  for (const message of [...olderMessages, ...existingMessages]) {
    if (seenIds.has(message.id)) continue
    seenIds.add(message.id)
    merged.push(message)
  }

  return merged
}
