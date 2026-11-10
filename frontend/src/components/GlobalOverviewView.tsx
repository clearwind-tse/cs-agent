// -*- coding: utf-8 -*-
/**
 * GlobalOverviewView — 全局总览（待办 / 统计 两个视角）
 *
 * 合并原因：原先「工作台」和「全局数据看板」是两个并列的全局入口，
 * 用户进来要先猜哪个更该点；其实它们是同一个问题的两面——
 *   待办 = 今天先做哪件；统计 = 数据有多少。
 * 现在收成一条入口，用同一页的 Tab 承载，URL 用 ?tab= 表达，刷新与分享都能落到同一视角。
 *
 * 两个子视图各自保留 header / 数据加载 / 降级逻辑，本组件只负责切页与提供 Tab。
 */
import { BarChart3, ListChecks } from 'lucide-react'
import { Tabs } from './ui'
import OverviewView from './OverviewView'
import WorkbenchView from './WorkbenchView'
import type { NavItem } from '../navigation'

export type OverviewTab = 'todo' | 'stats'

export const OVERVIEW_TABS: Array<{ key: OverviewTab; label: string; icon: JSX.Element }> = [
  { key: 'todo', label: '待办队列', icon: <ListChecks size={13} /> },
  { key: 'stats', label: '统计看板', icon: <BarChart3 size={13} /> },
]

interface GlobalOverviewViewProps {
  tab: OverviewTab
  onTabChange: (tab: OverviewTab) => void
  onNavigate: (item: NavItem) => void
}

export default function GlobalOverviewView({ tab, onTabChange, onNavigate }: GlobalOverviewViewProps) {
  const tabs = (
    <Tabs
      items={OVERVIEW_TABS}
      value={tab}
      onChange={(key) => onTabChange(key as OverviewTab)}
      className="ml-1"
    />
  )

  return tab === 'todo' ? (
    <WorkbenchView onNavigate={onNavigate} tabs={tabs} />
  ) : (
    <OverviewView onNavigate={onNavigate} tabs={tabs} />
  )
}
