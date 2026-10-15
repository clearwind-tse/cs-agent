/**
 * MCP 健康状态轮询 store（参考 DataClaw mcpHealthStore.ts）
 *
 * - 每 60 秒自动轮询一次 listMcpServers，检测是否有 error 状态
 * - 组件挂载时调用 startPolling(projectId)，卸载时调用 stopPolling
 * - 外部可通过 refresh() 手动触发一次
 */
import { create } from 'zustand'
import { listMcpServers } from '../api'
import type { McpServer } from '../api'

interface MCPHealthState {
  hasMcpError: boolean
  currentProjectId: number | null
  servers: McpServer[]
  lastRefreshAt: string | null
  startPolling: (projectId: number | null) => void
  stopPolling: () => void
  refresh: (projectId?: number | null) => Promise<void>
}

let pollingTimer: ReturnType<typeof setInterval> | null = null

export const useMcpHealthStore = create<MCPHealthState>((set, get) => ({
  hasMcpError: false,
  currentProjectId: null,
  servers: [],
  lastRefreshAt: null,

  refresh: async (projectIdArg?: number | null) => {
    const projectId = projectIdArg ?? get().currentProjectId
    try {
      // projectId 为空时不要短路返回空数组：传 null 表示「不过滤」，后端会返回全部（含全局）配置
      const data = await listMcpServers(projectId || null)
      const hasError = data.some((mcp) => Boolean(mcp.status && mcp.status.startsWith('error')))
      set({
        hasMcpError: hasError,
        currentProjectId: projectId || null,
        servers: data,
        lastRefreshAt: new Date().toLocaleTimeString(),
      })
    } catch (error) {
      console.error('[McpHealth] 健康检查失败:', error)
      set({ hasMcpError: true, currentProjectId: projectId || null })
    }
  },

  startPolling: (projectId: number | null) => {
    if (pollingTimer) {
      clearInterval(pollingTimer)
      pollingTimer = null
    }
    set({ currentProjectId: projectId ?? null })
    void get().refresh(projectId ?? null)
    pollingTimer = setInterval(() => { void get().refresh(projectId ?? null) }, 60_000)
  },

  stopPolling: () => {
    if (pollingTimer) {
      clearInterval(pollingTimer)
      pollingTimer = null
    }
  },
}))
