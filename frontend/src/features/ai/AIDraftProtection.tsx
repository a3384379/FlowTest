import { Modal, theme } from 'antd'
import { useContext, useEffect, type RefObject } from 'react'
import { UNSAFE_DataRouterContext, useBlocker } from 'react-router-dom'

type Props = {
  dirty: boolean
  allowLeaveRef: RefObject<boolean>
  title: string
  description: string
}
export default function AIDraftProtection(props: Props) {
  const dataRouter = useContext(UNSAFE_DataRouterContext)
  const { dirty, allowLeaveRef } = props
  useEffect(() => {
    if (!dirty) return
    const block = (event: BeforeUnloadEvent) => {
      if (!allowLeaveRef.current) event.preventDefault()
    }
    window.addEventListener('beforeunload', block)
    return () => window.removeEventListener('beforeunload', block)
  }, [dirty, allowLeaveRef])
  return dataRouter ? <AINavigationGuard {...props} /> : null
}
function AINavigationGuard({ dirty, allowLeaveRef, title, description }: Props) {
  const blocker = useBlocker(() => dirty && !allowLeaveRef.current)
  const { token } = theme.useToken()
  return (
    <Modal
      open={blocker.state === 'blocked'}
      zIndex={token.zIndexPopupBase + 100}
      title={title}
      okText="放弃修改并离开"
      cancelText="继续编辑"
      onOk={() => {
        allowLeaveRef.current = true
        blocker.proceed?.()
      }}
      onCancel={() => blocker.reset?.()}
    >
      {description}
    </Modal>
  )
}
