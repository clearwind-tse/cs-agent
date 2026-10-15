import type { Session } from '../types'

export interface ChatNavigationState {
  selectedSession: Session | null
  targetMessageId: number | null
}

type ChatNavigationAction =
  | { type: 'jump-to-message'; session: Session; messageId?: number | null }
  | { type: 'select-session'; session: Session }
  | { type: 'target-reached' }

export function reduceChatNavigationState(
  state: ChatNavigationState,
  action: ChatNavigationAction,
): ChatNavigationState {
  switch (action.type) {
    case 'jump-to-message':
      return {
        selectedSession: action.session,
        targetMessageId: action.messageId ?? null,
      }
    case 'select-session':
      return {
        selectedSession: action.session,
        targetMessageId: null,
      }
    case 'target-reached':
      return state
    default:
      return state
  }
}
