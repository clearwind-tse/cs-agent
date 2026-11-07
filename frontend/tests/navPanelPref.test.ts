import test from 'node:test'
import assert from 'node:assert/strict'

import {
  NAV_AUTO_COLLAPSE_KEY,
  readAutoCollapse,
  writeAutoCollapse,
} from '../src/navigationPref.ts'

test('自动折叠默认开启', () => {
  assert.equal(readAutoCollapse(null), true)
  assert.equal(readAutoCollapse({ getItem: () => null }), true)
})

test('关闭状态可写入并读回', () => {
  const data: Record<string, string> = {}
  const storage = {
    getItem: (key: string) => data[key] ?? null,
    setItem: (key: string, value: string) => { data[key] = value },
  }

  writeAutoCollapse(false, storage)
  assert.equal(data[NAV_AUTO_COLLAPSE_KEY], '0')
  assert.equal(readAutoCollapse(storage), false)

  writeAutoCollapse(true, storage)
  assert.equal(data[NAV_AUTO_COLLAPSE_KEY], '1')
  assert.equal(readAutoCollapse(storage), true)
})

test('存储不可用时回落默认且不抛异常', () => {
  const blockedRead = { getItem: () => { throw new Error('blocked') } }
  const blockedWrite = { setItem: () => { throw new Error('blocked') } }

  assert.equal(readAutoCollapse(blockedRead), true)
  assert.doesNotThrow(() => writeAutoCollapse(false, blockedWrite))
  assert.doesNotThrow(() => writeAutoCollapse(false, null))
})
