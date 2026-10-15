// 会话类型
export interface Session {
  id: number
  session_id: string
  display_name: string | null
  is_chatroom: boolean
  last_message: string | null
  last_time: number | null
  message_count: number
}

// 消息类型
export interface Message {
  id: number
  local_id: number | null
  session_id: string
  sender_wxid: string | null
  sender_name: string | null
  content: string | null
  msg_type: number
  is_sender: boolean
  timestamp: number
  display_content: string | null
  voice_path: string | null
}

// 联系人类型
export interface Contact {
  id: number
  wxid: string
  alias: string | null
  nickname: string | null
  remark: string | null
  display_name: string | null
  avatar_url: string | null
  is_chatroom: boolean
}

// 搜索结果
export interface SearchResult {
  id: number
  session_id: string
  session_name: string | null
  sender_name: string | null
  content: string | null
  timestamp: number
  msg_type: number
  highlight: string | null
}

// 分页响应
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

// 消息类型枚举
export const MSG_TYPES = {
  TEXT: 1,
  IMAGE: 3,
  VOICE: 34,
  VIDEO: 43,
  EMOJI: 47,
  LINK: 49,
  SYSTEM: 10000,
} as const
