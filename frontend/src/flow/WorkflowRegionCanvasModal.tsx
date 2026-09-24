import { Alert, Button, Modal, Select, Space, Typography } from 'antd'
import { useState } from 'react'
import type { ApiDefinition, WorkflowRegion } from '../lib/api'
import { insertRegionApiAfter, insertRegionDelayAfter } from './editor/control-blocks'
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
}: {
  region: WorkflowRegion
  editable: boolean
  selectedNodeId: string | null
  selectedNodeName?: string
  availableApis: ApiDefinition[]
  activeApiId?: string
  onSelectApi: (id: string) => void
  onInsert: (region: WorkflowRegion | null) => void
}) {
  return (
    <Space wrap className="workflow-region-canvas-toolbar">
      <Typography.Text>
        {selectedNodeName ? `已选中：${selectedNodeName}` : '选择步骤后可在其后插入节点'}
      </Typography.Text>
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
    </Space>
  )
}

function regionCanvasKey(region: WorkflowRegion): string {
  return JSON.stringify([
    region.nodes.map((node) => [node.id, node.name, node.position]),
    region.edges.map((edge) => [edge.id, edge.source, edge.target]),
  ])
}
