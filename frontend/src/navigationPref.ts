// -*- coding: utf-8 -*-
/**
 * navigationPref.ts — 功能地图面板的显示偏好
 *
 * 纯函数 + 可注入 storage，便于在没有 DOM 的环境里验证默认值、持久化与容错。
 * 自动折叠默认开启：点击功能跳转后面板收起，不长期占用内容宽度。
 * 关闭后面板保持展开，并在宽屏切换为停靠布局（把内容推右，不遮挡）。
 */
export const NAV_AUTO_COLLAPSE_KEY = 'acp-nav-autocollapse'

type ReadableStorage = { getItem(key: string): string | null }
type WritableStorage = { setItem(key: string, value: string): void }

export function readAutoCollapse(storage?: ReadableStorage | null): boolean {
  if (!storage) return true
  try {
    return storage.getItem(NAV_AUTO_COLLAPSE_KEY) !== '0'
  } catch {
    return true
  }
}

export function writeAutoCollapse(value: boolean, storage?: WritableStorage | null): void {
  if (!storage) return
  try {
    storage.setItem(NAV_AUTO_COLLAPSE_KEY, value ? '1' : '0')
  } catch {
    // 隐私模式 / 配额满：偏好只在本会话内生效，不打断导航
  }
}

export function getBrowserStorage(): (ReadableStorage & WritableStorage) | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}
