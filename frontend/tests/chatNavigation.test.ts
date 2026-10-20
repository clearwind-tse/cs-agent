import test from 'node:test'
import assert from 'node:assert/strict'

import { reduceChatNavigationState } from '../src/components/chatNavigation.ts'

test('search jump keeps target message after target reached', () => {
  const jumped = reduceChatNavigationState(
    { selectedSession: null, targetMessageId: null },
    {
      type: 'jump-to-message',
      session: {
        id: 1,
        session_id: 'wxid_demo',
        display_name: 'Demo',
        is_chatroom: false,
        last_message: null,
        last_time: null,
        message_count: 1,
      },
      messageId: 123,
    },
  )

  const afterReached = reduceChatNavigationState(jumped, { type: 'target-reached' })

  assert.equal(afterReached.targetMessageId, 123)
})

test('manual session select clears target message', () => {
  const state = reduceChatNavigationState(
    {
      selectedSession: {
        id: 1,
        session_id: 'wxid_demo',
        display_name: 'Demo',
        is_chatroom: false,
        last_message: null,
        last_time: null,
        message_count: 1,
      },
      targetMessageId: 123,
    },
    {
      type: 'select-session',
      session: {
        id: 2,
        session_id: 'wxid_demo_2',
        display_name: 'Demo2',
        is_chatroom: false,
        last_message: null,
        last_time: null,
        message_count: 1,
      },
    },
  )

  assert.equal(state.targetMessageId, null)
  assert.equal(state.selectedSession?.session_id, 'wxid_demo_2')
})
