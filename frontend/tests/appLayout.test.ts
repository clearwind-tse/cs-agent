import test from 'node:test'
import assert from 'node:assert/strict'

import { getAppMainLayoutClasses } from '../src/appLayout.ts'

test('app main content preserves nested scroll containers', () => {
  const classes = getAppMainLayoutClasses()

  assert.match(classes.main, /\bflex-1\b/)
  assert.match(classes.main, /\bmin-w-0\b/)
  assert.match(classes.main, /\bmin-h-0\b/)
  assert.match(classes.main, /\boverflow-hidden\b/)
})
