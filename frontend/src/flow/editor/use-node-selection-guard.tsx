import { Button, Modal, Space } from 'antd'
import { useEffect, useRef, useState } from 'react'
import type { DraftSession } from '../../features/drafts/draft-session'

export function useNodeSelectionGuard(session: DraftSession, scope: string, editable: boolean) {
  const [open, setOpen] = useState(false)
  const [applying, setApplying] = useState(false)
  const pending = useRef<((value: boolean) => void) | null>(null)
  useEffect(
    () => () => {
      pending.current?.(false)
    },
    [],
  )

  function request(): Promise<boolean> {
    if (!editable || !session.dirtyNodeEditorKeys(scope).length) return Promise.resolve(true)
    if (pending.current) return Promise.resolve(false)
    setOpen(true)
    return new Promise((resolve) => {
      pending.current = resolve
    })
  }

  async function finish(action: 'apply' | 'discard' | 'cancel') {
    if (applying) return
    const keys = session.dirtyNodeEditorKeys(scope)
    let proceed = action !== 'cancel'
    if (action === 'apply') {
      setApplying(true)
      for (const key of keys) {
        if (!(await session.nodeEditorActions.get(key)?.())) {
          proceed = false
          break
        }
      }
      setApplying(false)
    }
    if (action === 'discard') keys.forEach((key) => session.clearNodeEditor(key))
    const resolve = pending.current
    pending.current = null
    setOpen(false)
    resolve?.(proceed)
  }

  return {
    request,
    dialog: (
      <Modal
        title="节点配置尚未应用"
        aria-label="节点配置尚未应用"
        open={open}
        onCancel={() => void finish('cancel')}
        closable={!applying}
        footer={
          <Space wrap>
            <Button disabled={applying} onClick={() => void finish('cancel')}>
              取消切换
            </Button>
            <Button danger disabled={applying} onClick={() => void finish('discard')}>
              丢弃此节点修改
            </Button>
            <Button type="primary" loading={applying} onClick={() => void finish('apply')}>
              应用配置后继续
            </Button>
          </Space>
        }
      >
        切换节点前，选择将当前输入应用到图草稿、丢弃本次节点输入，或留在当前节点继续编辑。
      </Modal>
    ),
  }
}
