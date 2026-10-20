import test from 'node:test'
import assert from 'node:assert/strict'

import {
  calculateTargetScrollTop,
  shouldAutoLoadMoreOnScroll,
} from '../src/components/chatPositioning.ts'

test('calculateTargetScrollTop centers target bubble inside container', () => {
  const top = calculateTargetScrollTop({
    containerHeight: 600,
    contentHeight: 2000,
    targetOffsetTop: 900,
    targetHeight: 80,
  })

  assert.equal(top, 640)
})

test('calculateTargetScrollTop clamps to top and bottom edges', () => {
  assert.equal(
    calculateTargetScrollTop({
      containerHeight: 600,
      contentHeight: 2000,
      targetOffsetTop: 50,
      targetHeight: 80,
    }),
    0,
  )

  assert.equal(
    calculateTargetScrollTop({
      containerHeight: 600,
      contentHeight: 2000,
      targetOffsetTop: 1900,
      targetHeight: 80,
    }),
    1400,
  )
})

test('shouldAutoLoadMoreOnScroll skips auto paging while target jump is positioning', () => {
  assert.equal(
    shouldAutoLoadMoreOnScroll({
      hasMore: true,
      loadingMore: false,
      scrollTop: 20,
      isTargetPositioning: true,
    }),
    false,
  )
})

test('shouldAutoLoadMoreOnScroll still loads when user scrolls near top normally', () => {
  assert.equal(
    shouldAutoLoadMoreOnScroll({
      hasMore: true,
      loadingMore: false,
      scrollTop: 20,
      isTargetPositioning: false,
    }),
    true,
  )
})
