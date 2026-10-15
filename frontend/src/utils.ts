import { format, formatDistanceToNow, isToday, isYesterday, isThisWeek } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

// 合并 className
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// 格式化时间戳
export function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000)
  
  if (isToday(date)) {
    return format(date, 'HH:mm')
  }
  
  if (isYesterday(date)) {
    return '昨天 ' + format(date, 'HH:mm')
  }
  
  if (isThisWeek(date)) {
    return format(date, 'EEEE HH:mm', { locale: zhCN })
  }
  
  return format(date, 'MM-dd HH:mm')
}

// 格式化完整日期时间
export function formatDateTime(timestamp: number | string | null | undefined): string {
  if (!timestamp) return ''
  
  let date: Date
  if (typeof timestamp === 'string') {
    // ISO 字符串格式
    date = new Date(timestamp)
  } else {
    // 数字时间戳（秒）
    date = new Date(timestamp * 1000)
  }
  
  // 检查日期是否有效
  if (isNaN(date.getTime())) {
    return ''
  }
  
  return format(date, 'yyyy年MM月dd日 HH:mm:ss', { locale: zhCN })
}

// 格式化相对时间
export function formatRelative(timestamp: number): string {
  const date = new Date(timestamp * 1000)
  return formatDistanceToNow(date, { addSuffix: true, locale: zhCN })
}

// 截断文本
export function truncate(text: string | null, maxLength: number): string {
  if (!text) return ''
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength) + '...'
}

// 获取消息类型标签
export function getMsgTypeLabel(type: number): string {
  const labels: Record<number, string> = {
    1: '文本',
    3: '图片',
    34: '语音',
    43: '视频',
    47: '表情',
    49: '链接/文件',
    10000: '系统消息',
  }
  return labels[type] || `未知(${type})`
}

// 生成头像颜色
export function getAvatarColor(name: string): string {
  const colors = [
    'from-pink-500 to-rose-500',
    'from-purple-500 to-indigo-500',
    'from-blue-500 to-cyan-500',
    'from-teal-500 to-emerald-500',
    'from-green-500 to-lime-500',
    'from-yellow-500 to-orange-500',
    'from-orange-500 to-red-500',
  ]
  
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  
  return colors[Math.abs(hash) % colors.length]
}

// 获取名字首字母
export function getInitials(name: string | null): string {
  if (!name) return '?'
  return name.charAt(0).toUpperCase()
}
