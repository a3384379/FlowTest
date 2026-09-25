import { Alert, Button, Modal, Popconfirm, Select, Space, Typography } from 'antd'
import { useState } from 'react'
import type { ApiDefinition, WorkflowRegion } from '../lib/api'
import {
  insertRegionApiAfter,
  insertRegionDelayAfter,
  moveRegionStep,
  removeRegionStep,
} from './editor/control-blocks'
import WorkflowRegionCanvas from './WorkflowRegionCanvas'

type Props = {
  open: boolean
  region: WorkflowRegion
  apis: ApiDefinition[]
  editable: boolean
  onClose: () => void
  onUpdate: (region: WorkflowRegion) => void
}

export default function WorkflowRegionCanvasModal({
  open,
  region,
  apis,
  editable,
  onClose,
  onUpdate,
}: Props) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedApiId, setSelectedApiId] = useState<string | undefined>()
  const [error, setError] = useState<string | null>(null)
  const selectedNode = region.nodes.find((node) => node.id === selectedNodeId)
  const availableApis = apis.filter((api) => api.is_active)
  const activeApiId = selectedApiId ?? availableApis[0]?.id
  function applyInsertion(next: WorkflowRegion | null) {
    if (!next) {
      setError('选中步骤的连线无法安全插入；请先整理区域连线与字段映射。')
      return
    }
    onUpdate(next)
    setSelectedNodeId(
      next.nodes.find((node) => !region.nodes.some((old) => old.id === node.id))?.id ?? null,
    )
    setError(null)
  }
  function applyDeletion() {
    if (!selectedNodeId) return
    const next = removeRegionStep(region, selectedNodeId)
    if (!next) {
      setError('该步骤不能安全删除：请检查区域边界、条件连线、字段映射或剩余节点引用。')
      return
    }
    onUpdate(next)
    setSelectedNodeId(null)
    setError(null)
  }
  function applyMove(direction: -1 | 1) {
    if (!selectedNodeId) return
    const next = moveRegionStep(region, selectedNodeId, direction)
    if (!next) {
      setError('只能重排无条件、无字段映射且没有节点引用的线性区域步骤。')
      return
    }
    onUpdate(next)
    setError(null)
  }
  return (
    <Modal
      title={`${region.role} 区域画布`}
      open={open}
      width={960}
      footer={null}
      onCancel={() => {
        setSelectedNodeId(null)
        onClose()
      }}
    >
      <CanvasToolbar
        region={region}
        editable={editable}
        selectedNodeId={selectedNode?.id ?? null}
        selectedNodeName={selectedNode?.name}
        availableApis={availableApis}
        activeApiId={activeApiId}
        onSelectApi={setSelectedApiId}
        onInsert={applyInsertion}
        onMove={applyMove}
        onRemove={applyDeletion}
      />
      {error && <Alert type="error" title={error} />}
      <WorkflowRegionCanvas
        key={regionCanvasKey(region)}
        region={region}
        editable={editable}
        selectedNodeId={selectedNodeId}
        onSelectNode={setSelectedNodeId}
        onUpdate={onUpdate}
      />
    </Modal>
  )
}

function CanvasToolbar({
  region,
  editable,
  selectedNodeId,
  selectedNodeName,
  availableApis,
  activeApiId,
  onSelectApi,
  onInsert,
  onMove,
  onRemove,
}: {
  region: WorkflowRegion
  editable: boolean
  selectedNodeId: string | null
  selectedNodeName?: string
  availableApis: ApiDefinition[]
  activeApiId?: string
  onSelectApi: (id: string) => void
  onInsert: (region: WorkflowRegion | null) => void
  onMove: (direction: -1 | 1) => void
  onRemove: () => void
}) {
  return (
    <Space wrap className="workflow-region-canvas-toolbar">
      <Typography.Text>
        {selectedNodeName ? `已选中：${selectedNodeName}` : '选择步骤后可在其后插入节点'}
      </Typography.Text>
      <MoveButtons editable={editable} selectedNodeId={selectedNodeId} onMove={onMove} />
      <Button
        disabled={!editable || !selectedNodeId}
        onClick={() => {
          if (selectedNodeId) onInsert(insertRegionDelayAfter(region, selectedNodeId))
        }}
      >
        在后面插入等待
      </Button>
      {availableApis.length > 0 && (
        <>
          <Select
            aria-label={`${region.role} 画布待插入接口`}
            value={activeApiId}
            disabled={!editable || !selectedNodeId}
            options={availableApis.map((api) => ({ value: api.id, label: api.name }))}
            onChange={onSelectApi}
            style={{ minWidth: 150 }}
          />
          <Button
            disabled={!editable || !selectedNodeId || !activeApiId}
            onClick={() => {
              const api = availableApis.find((item) => item.id === activeApiId)
              if (api && selectedNodeId)
                onInsert(insertRegionApiAfter(region, selectedNodeId, api.id, api.current_version))
            }}
          >
            在后面插入接口
          </Button>
        </>
      )}
      <Popconfirm
        title="删除区域步骤"
        description="将删除所选步骤并安全重接线性连线；草稿可撤销。"
        disabled={!editable || !selectedNodeId}
        onConfirm={onRemove}
      >
        <Button danger disabled={!editable || !selectedNodeId}>
          删除所选步骤
        </Button>
      </Popconfirm>
    </Space>
  )
}

function MoveButtons({
  editable,
  selectedNodeId,
  onMove,
}: {
  editable: boolean
  selectedNodeId: string | null
  onMove: (direction: -1 | 1) => void
}) {
  const disabled = !editable || !selectedNodeId
  return (
    <>
      <Button disabled={disabled} onClick={() => onMove(-1)}>
        向前移动
      </Button>
      <Button disabled={disabled} onClick={() => onMove(1)}>
        向后移动
      </Button>
    </>
  )
}

function regionCanvasKey(region: WorkflowRegion): string {
  return JSON.stringify([
    region.nodes.map((node) => [node.id, node.name, node.position]),
    region.edges.map((edge) => [edge.id, edge.source, edge.target]),
  ])
}
