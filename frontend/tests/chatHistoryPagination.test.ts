import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getHistoryRequestPage,
  prependUniqueMessages,
} from '../src/components/chatHistoryPagination.ts'

test('load more requests the next history page instead of the current one', () => {
  assert.deepEqual(
    getHistoryRequestPage({ currentPage: 1, reset: false }),
    { pageToLoad: 2, nextPage: 2 },
  )
})

test('reset always requests the first history page', () => {
  assert.deepEqual(
    getHistoryRequestPage({ currentPage: 7, reset: true }),
    { pageToLoad: 1, nextPage: 1 },
  )
})

test('prependUniqueMessages drops duplicate message ids when older pages overlap', () => {
  const merged = prependUniqueMessages(
    [
      { id: 3 },
      { id: 4 },
      { id: 5 },
    ],
    [
      { id: 1 },
      { id: 2 },
      { id: 3 },
    ],
  )

  assert.deepEqual(merged.map(item => item.id), [1, 2, 3, 4, 5])
})
