import { useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { Alert, Modal } from 'antd'
import { UNSAFE_DataRouterContext, useBlocker } from 'react-router-dom'
import { DraftContext, DraftSession } from './draft-session'

export function DraftSessionProvider({ children }: { children: ReactNode }) {
  const [session] = useState(() => new DraftSession())
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
          title="部分草稿仅保存在当前会话内存中，刷新或关闭浏览器前请返回编辑页保存。"
        />
      )}
      {dataRouter && <DraftNavigationGuard unsafe={unsafe} />}
    </>
  )
}
function DraftNavigationGuard({ unsafe }: { unsafe: boolean }) {
  const blocker = useBlocker(unsafe)
  return (
    <Modal
      open={blocker.state === 'blocked'}
      title="草稿尚未持久化"
      okText="保留草稿并切换"
      cancelText="留在当前页保存"
      onOk={() => blocker.proceed?.()}
      onCancel={() => blocker.reset?.()}
    >
      当前浏览器无法保存草稿。切换后草稿会保留在本次会话，返回原项目和资源可继续编辑；请勿刷新或关闭浏览器。
    </Modal>
  )
}
