/**
 * 会话 ID 的展示脱敏工具。
 *
 * 背景：库内 session_id 为微信导出的原始 `wxid_拼音数字` 形态，直接展示会暴露
 * 数据来源且观感不真实。此处仅在**展示层**做脱敏，真实 ID 仍原样用于 API 请求与路由，
 * 不改变任何后端契约。
 *
 * 脱敏值是 FNV-1a 32 位哈希的确定性前缀 —— 同一 session_id 恒定映射同一标识，
 * 因此列表/表格中的不同会话仍可区分，且刷新、翻页、跨页签保持一致。
 */

/** 会话 ID → 短标识，如 `#A3F2C8`；空值返回空串。 */
export function maskSessionId(id?: string | null): string {
  if (!id) return ''

  let hash = 2166136261
  for (let i = 0; i < id.length; i += 1) {
    hash ^= id.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }

  return `#${(hash >>> 0).toString(16).toUpperCase().padStart(8, '0').slice(0, 6)}`
}

/** 会话显示名：优先真实昵称，缺失时回退到脱敏标识，绝不回退到原始 ID。 */
export function sessionLabel(name?: string | null, sessionId?: string | null): string {
  if (name) return name

  const masked = maskSessionId(sessionId)
  return masked ? `会话 ${masked}` : '未命名会话'
}
