import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildChatPath,
  buildViewPath,
  getChatRouteState,
  getViewModeFromPath,
} from '../src/appRoutes.ts'

test('getViewModeFromPath maps top-level paths to views', () => {
  assert.equal(getViewModeFromPath('/search'), 'search')
  assert.equal(getViewModeFromPath('/overview'), 'overview')
  assert.equal(getViewModeFromPath('/unknown-path'), 'chat')
  assert.equal(getViewModeFromPath('/chat/wxid_123'), 'chat')
  assert.equal(getViewModeFromPath('/'), 'chat')
})

test('buildChatPath encodes session id and message id', () => {
  assert.equal(buildChatPath(), '/chat')
  assert.equal(buildChatPath('wxid_abc'), '/chat/wxid_abc')
  assert.equal(buildChatPath('room/1', 42), '/chat/room%2F1?messageId=42')
})

test('buildViewPath returns expected non-chat paths', () => {
  assert.equal(buildViewPath('admin'), '/admin')
  assert.equal(buildViewPath('quiz'), '/quiz')
  assert.equal(buildViewPath('overview'), '/overview')
})

test('getChatRouteState parses session id and message id from location', () => {
  assert.deepEqual(
    getChatRouteState('/chat/room%2F1', '?messageId=42'),
    { sessionId: 'room/1', messageId: 42 },
  )
  assert.deepEqual(
    getChatRouteState('/unknown-path', ''),
    { sessionId: null, messageId: null },
  )
  assert.deepEqual(
    getChatRouteState('/chat', '?messageId=abc'),
    { sessionId: null, messageId: null },
  )
})
