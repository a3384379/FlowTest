import { App, Alert, Button, Input, Modal, Space, Typography } from 'antd'
import { useState } from 'react'

import { apiErrorMessage, type Workflow } from '../../lib/api'
import {
  exportNativeWorkflow,
  importNativeWorkflow,
  type NativeWorkflowDocument,
} from './workflow-service'

type Props = {
  open: boolean
  projectId: string
  workflowId: string | null
  canEdit: boolean
  onClose: () => void
  onImported: (workflow: Workflow) => Promise<void>
}

export default function NativeWorkflowTransferDialog(props: Props) {
  const { message } = App.useApp()
  const [raw, setRaw] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  async function exportCurrent() {
    if (!props.workflowId) return
    setBusy(true)
    try {
      const document = await exportNativeWorkflow(props.projectId, props.workflowId)
      const content = JSON.stringify(document, null, 2)
      setRaw(content)
      setName(`${document.name} 副本`)
      const url = URL.createObjectURL(new Blob([content], { type: 'application/json' }))
      const link = window.document.createElement('a')
      link.href = url
      link.download = `flowtest-workflow-${props.workflowId}.json`
      link.click()
      URL.revokeObjectURL(url)
      void message.success('服务器草稿已导出')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function importDocument() {
    let document: NativeWorkflowDocument
    try {
      document = parseDocument(raw)
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '原生工作流 JSON 无效')
      return
    }
    setBusy(true)
    try {
      const imported = await importNativeWorkflow(props.projectId, {
        ...document,
        name: name.trim() || `${document.name} 副本`,
      })
      await props.onImported(imported)
      void message.success('已导入为未发布草稿')
      close()
    } catch (error) {
      void message.error(apiErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function loadFile(file: File | undefined) {
    if (!file) return
    if (file.size > 2_000_000) {
      void message.error('原生定义文件不能超过 2 MB')
      return
    }
    try {
      setRaw(await file.text())
      setName('')
    } catch {
      void message.error('原生定义文件读取失败')
    }
  }

  function close() {
    setRaw('')
    setName('')
    props.onClose()
  }

  return (
    <Modal open={props.open} title="原生工作流定义导入 / 导出" footer={null} onCancel={close}>
      <Space orientation="vertical" className="workflow-transfer-form" style={{ width: '100%' }}>
        <Alert
          type="info"
          showIcon
          description="导出使用服务器已保存的草稿。导入会创建未发布的新草稿；定义引用的接口和子流程须在当前项目可用。"
        />
        <Button
          disabled={!props.workflowId || busy}
          loading={busy}
          onClick={() => void exportCurrent()}
        >
          导出服务器草稿 JSON
        </Button>
        <Typography.Text>原生定义 JSON</Typography.Text>
        <input
          aria-label="选择原生定义文件"
          type="file"
          accept=".json,application/json"
          onChange={(event) => {
            void loadFile(event.target.files?.[0])
            event.target.value = ''
          }}
        />
        <Input.TextArea
          aria-label="原生定义 JSON"
          rows={12}
          value={raw}
          onChange={(event) => setRaw(event.target.value)}
          placeholder="粘贴 flowtest-workflow-native-v1 JSON"
        />
        <Input
          aria-label="新流程名称"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="留空则使用原名称加“副本”"
        />
        <Button
          type="primary"
          disabled={!props.canEdit || !raw.trim() || busy}
          loading={busy}
          onClick={() => void importDocument()}
        >
          导入为新草稿
        </Button>
      </Space>
    </Modal>
  )
}

function parseDocument(raw: string): NativeWorkflowDocument {
  if (raw.length > 2_000_000) throw new Error('原生工作流 JSON 不能超过 2 MB')
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    throw new Error('原生工作流 JSON 语法无效')
  }
  if (!isNativeWorkflowDocument(value)) {
    throw new Error('需要 flowtest-workflow-native-v1 原生工作流定义')
  }
  return value
}

function isNativeWorkflowDocument(value: unknown): value is NativeWorkflowDocument {
  if (!isRecord(value)) return false
  if (value.format_version !== 'flowtest-workflow-native-v1') return false
  if (typeof value.name !== 'string' || typeof value.description !== 'string') return false
  return isRecord(value.definition)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
