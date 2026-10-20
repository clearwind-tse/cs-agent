import test from 'node:test'
import assert from 'node:assert/strict'

import { getSearchViewLayoutClasses } from '../src/components/searchViewLayout.ts'

test('search view root enables nested scrolling in flex layout', () => {
  const classes = getSearchViewLayoutClasses()

  assert.match(classes.root, /\bh-full\b/)
  assert.match(classes.root, /\bmin-h-0\b/)
  assert.match(classes.root, /\boverflow-hidden\b/)
  assert.match(classes.results, /\bmin-h-0\b/)
  assert.match(classes.results, /\boverflow-y-auto\b/)
})
