function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

export function calculateTargetScrollTop(params: {
  containerHeight: number
  contentHeight: number
  targetOffsetTop: number
  targetHeight: number
}) {
  const { containerHeight, contentHeight, targetOffsetTop, targetHeight } = params
  const maxScrollTop = Math.max(0, contentHeight - containerHeight)
  const centeredTop = targetOffsetTop - (containerHeight - targetHeight) / 2
  return clamp(Math.round(centeredTop), 0, maxScrollTop)
}

export function shouldAutoLoadMoreOnScroll(params: {
  hasMore: boolean
  loadingMore: boolean
  scrollTop: number
  isTargetPositioning: boolean
}) {
  const { hasMore, loadingMore, scrollTop, isTargetPositioning } = params
  return hasMore && !loadingMore && !isTargetPositioning && scrollTop < 100
}
