import test from 'node:test'
import assert from 'node:assert/strict'

import { getErrorMessage } from '../src/utils/errorMessage.ts'

test('returns string detail directly', () => {
  const err = { response: { data: { detail: '请求失败' } } }
  assert.equal(getErrorMessage(err, 'fallback'), '请求失败')
})

test('joins validation detail array messages', () => {
  const err = {
    response: {
      data: {
        detail: [
          { msg: 'Input should be less than or equal to 100' },
          { msg: 'Another validation error' },
        ],
      },
    },
  }
  assert.equal(
    getErrorMessage(err, 'fallback'),
    'Input should be less than or equal to 100；Another validation error',
  )
})

test('falls back safely for unknown detail object', () => {
  const err = { response: { data: { detail: { loc: ['query', 'page_size'] } } } }
  assert.equal(getErrorMessage(err, '学员列表加载失败'), '学员列表加载失败')
})
