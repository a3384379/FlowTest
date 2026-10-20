import {
  useContext,
  useEffect,
  useLayoutEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react'
import { Alert, Modal } from 'antd'
import { useAuthStore } from '../auth/auth-store'
import { UNSAFE_DataRouterContext, useBlocker } from 'react-router-dom'
import {
  REQUEST_TARGET_DRAFT_PREFIX,
  DRAFT_NAVIGATION_CANCELLED,
  DraftContext,
  DraftSession,
} from './draft-session'

export function DraftSessionProvider({ children }: { children: ReactNode }) {
  const [session] = useState(() => new DraftSession())
  const phase = useAuthStore((state) => state.phase)
  useLayoutEffect(() => {
    if (phase === 'anonymous' || phase === 'logging-out') session.clearProtocolRequests()
  }, [phase, session])
  return (
    <DraftContext.Provider value={session}>
      <DraftProtection session={session} />
      {children}
    </DraftContext.Provider>
  )
}
function DraftProtection({ session }: { session: DraftSession }) {
  useSyncExternalStore(session.subscribe, session.snapshot)
  const dataRouter = useContext(UNSAFE_DataRouterContext)
  const unsafe = session.unsafe.size > 0
  const discarding = [...session.unsafe].some((key) => key.startsWith(REQUEST_TARGET_DRAFT_PREFIX))
  useEffect(() => {
    if (!unsafe) return
    const block = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', block)
    return () => window.removeEventListener('beforeunload', block)
  }, [unsafe])
  return (
    <>
      {unsafe && (
        <Alert
          type="warning"
          showIcon
          title={
            discarding
              ? '请求目标候选尚未保存，离开编辑页前请保存或明确放弃。'
              : '部分草稿仅保存在当前会话内存中，刷新或关闭浏览器前请返回编辑页保存。'
          }
        />
      )}
      {dataRouter && <DraftNavigationGuard unsafe={unsafe} discarding={discarding} />}
    </>
  )
}
function DraftNavigationGuard({ unsafe, discarding }: { unsafe: boolean; discarding: boolean }) {
  const blocker = useBlocker(({ currentLocation, nextLocation }) => {
    const protocolQuery =
      currentLocation.pathname === nextLocation.pathname &&
      /\/projects\/[^/]+\/protocols$/.test(currentLocation.pathname)
    return unsafe && (discarding || !protocolQuery)
  })
  return (
    <Modal
      open={blocker.state === 'blocked'}
      title={discarding ? '请求目标候选尚未保存' : '草稿尚未持久化'}
      okText={discarding ? '放弃候选并切换' : '保留草稿并切换'}
      cancelText="留在当前页保存"
      onOk={() => blocker.proceed?.()}
      onCancel={() => {
        blocker.reset?.()
        window.dispatchEvent(new Event(DRAFT_NAVIGATION_CANCELLED))
      }}
    >
      {discarding
        ? '请求目标候选只保存在当前编辑页，切换将放弃本次候选，服务器配置不变。其他模块保存在会话中的草稿继续保留。'
        : '尚未应用的节点配置或未持久化草稿仅保留在本次会话。切换后返回原项目和资源可继续编辑；刷新、关闭浏览器或退出登录会丢失这些输入。'}
    </Modal>
  )
}
