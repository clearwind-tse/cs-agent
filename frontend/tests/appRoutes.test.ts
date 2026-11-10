import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildChatPath,
  buildStudioPath,
  buildViewPath,
  getChatRouteState,
  getStudioPaneFromPath,
  getViewModeFromPath,
  type StudioPane,
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
  assert.equal(buildViewPath('settings'), '/settings')
})

test('设置是全局工具视图，URL 可往返且不误伤同名前缀', () => {
  assert.equal(getViewModeFromPath('/settings'), 'settings')
  assert.equal(getViewModeFromPath('/settings/'), 'settings')
  assert.equal(getViewModeFromPath('/settings-extra'), 'chat')
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

test('AI 创作的子页面共用 studio 视图，且可通过 URL 往返', () => {
  // 子页不能各自成为独立视图，否则导航条与面包屑会把 8 个功能当成 8 个一级入口
  assert.equal(getViewModeFromPath('/studio'), 'studio')
  assert.equal(getViewModeFromPath('/studio/set'), 'studio')
  assert.equal(getViewModeFromPath('/studio/retouch/'), 'studio')
  // 前缀匹配不能误伤同名开头的路径
  assert.equal(getViewModeFromPath('/studiox'), 'chat')

  const panes: StudioPane[] = [
    'home', 'set', 'style', 'sku', 'outfit', 'retouch', 'canvas', 'assets', 'endpoints',
  ]
  for (const pane of panes) {
    assert.equal(getStudioPaneFromPath(buildStudioPath(pane)), pane)
  }
  // 图像端点是第五组 IA 的独立子页，不是嵌在设置里的一个 Tab
  assert.equal(buildStudioPath('endpoints'), '/studio/endpoints')
  assert.equal(getStudioPaneFromPath('/studio/endpoints/'), 'endpoints')

  // 未知子路径落回首页，而不是留在空白页
  assert.equal(getStudioPaneFromPath('/studio/unknown'), 'home')
  assert.equal(buildViewPath('studio'), '/studio')
})
