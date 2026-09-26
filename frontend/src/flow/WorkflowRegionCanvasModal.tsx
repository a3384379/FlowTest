import { Alert, Button, Modal, Popconfirm, Select, Space, Typography } from 'antd'
import { useState, type ReactNode } from 'react'
import type { ApiDefinition, WorkflowDefinition, WorkflowNode, WorkflowRegion } from '../lib/api'
import {
  insertNestedControlBlock,
  insertRegionApiAfter,
  insertRegionDelayAfter,
  linearRegionPath,
  moveRegionStep,
  moveRegionStepTo,
  removeNestedControlBlock,
  removeRegionStep,
  type ControlBlockKind,
} from './editor/control-blocks'
import WorkflowRegionCanvas from './WorkflowRegionCanvas'

type Props = {
  open: boolean
  region: WorkflowRegion
  definition?: WorkflowDefinition
  apis: ApiDefinition[]
  editable: boolean
  onClose: () => void
  onUpdate: (region: WorkflowRegion) => void
  onStructureChange?: (definition: WorkflowDefinition) => void
  renderNestedControl?: (node: WorkflowNode, region: WorkflowRegion) => ReactNode
}

export default function WorkflowRegionCanvasModal({
  open,
  region,
  definition,
  apis,
  editable,
  onClose,
  onUpdate,
  onStructureChange,
  renderNestedControl,
}: Props) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedApiId, setSelectedApiId] = useState<string | undefined>()
  const [controlKind, setControlKind] = useState<ControlBlockKind>('group')
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
    if (selectedNode?.capability_id?.startsWith('flow.control.')) {
      const next = definition && removeNestedControlBlock(definition, region.id, selectedNodeId)
      if (!next) {
        setError('该嵌套控制块仍有条件连线、字段映射或节点引用，不能安全删除。')
        return
      }
      onStructureChange?.(next)
      setSelectedNodeId(null)
      setError(null)
      return
    }
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
  function applyMoveTo(targetIndex: number) {
    if (!selectedNodeId) return
    const next = moveRegionStepTo(region, selectedNodeId, targetIndex)
    if (!next) {
      setError('只能重排无条件、无字段映射且没有节点引用的线性区域步骤。')
      return
    }
    onUpdate(next)
    setError(null)
  }
  function applyNestedInsertion() {
    if (!selectedNodeId || !definition) return
    const next = insertNestedControlBlock(definition, region.id, selectedNodeId, controlKind)
    if (!next) {
      setError('不能在此处插入控制块：请检查区域深度、出口和条件或字段映射连线。')
      return
    }
    onStructureChange?.(next)
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
        controlKind={controlKind}
        onSelectControlKind={setControlKind}
        canInsertControl={Boolean(definition && onStructureChange)}
        onInsertControl={applyNestedInsertion}
        onMove={applyMove}
        onMoveTo={applyMoveTo}
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
      <NestedControlConfiguration
        node={selectedNode}
        region={region}
        renderNestedControl={renderNestedControl}
      />
      <NestedRegionNavigation
        open={open}
        ownerId={selectedNodeId}
        definition={definition}
        apis={apis}
        editable={editable}
        onUpdate={onUpdate}
        onStructureChange={onStructureChange}
        renderNestedControl={renderNestedControl}
      />
    </Modal>
  )
}

function NestedControlConfiguration({
  node,
  region,
  renderNestedControl,
}: {
  node?: WorkflowNode
  region: WorkflowRegion
  renderNestedControl?: (node: WorkflowNode, region: WorkflowRegion) => ReactNode
}) {
  if (!node?.capability_id?.startsWith('flow.control.')) return null
  return renderNestedControl?.(node, region)
}

function NestedRegionNavigation({
  open,
  ownerId,
  definition,
  apis,
  editable,
  onUpdate,
  onStructureChange,
  renderNestedControl,
}: {
  open: boolean
  ownerId: string | null
  definition?: WorkflowDefinition
  apis: ApiDefinition[]
  editable: boolean
  onUpdate: (region: WorkflowRegion) => void
  onStructureChange?: (definition: WorkflowDefinition) => void
  renderNestedControl?: (node: WorkflowNode, region: WorkflowRegion) => ReactNode
}) {
  const [openChildId, setOpenChildId] = useState<string | null>(null)
  const childRegions = definition?.regions?.filter((item) => item.owner_node_id === ownerId) ?? []
  const openChild = childRegions.find((item) => item.id === openChildId)
  if (!open || !ownerId || childRegions.length === 0) return null
  return (
    <>
      <Space wrap>
        <Typography.Text>嵌套控制区域</Typography.Text>
        {childRegions.map((child) => (
          <Button key={child.id} onClick={() => setOpenChildId(child.id)}>
            打开嵌套 {child.role} 区域
          </Button>
        ))}
      </Space>
      {openChild && (
        <WorkflowRegionCanvasModal
          open
          region={openChild}
          definition={definition}
          apis={apis}
          editable={editable}
          onClose={() => setOpenChildId(null)}
          onUpdate={onUpdate}
          onStructureChange={onStructureChange}
          renderNestedControl={renderNestedControl}
        />
      )}
    </>
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
  controlKind,
  onSelectControlKind,
  canInsertControl,
  onInsertControl,
  onMove,
  onMoveTo,
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
  controlKind: ControlBlockKind
  onSelectControlKind: (kind: ControlBlockKind) => void
  canInsertControl: boolean
  onInsertControl: () => void
  onMove: (direction: -1 | 1) => void
  onMoveTo: (targetIndex: number) => void
  onRemove: () => void
}) {
  return (
    <Space wrap className="workflow-region-canvas-toolbar">
      <Typography.Text>
        {selectedNodeName ? `已选中：${selectedNodeName}` : '选择步骤后可在其后插入节点'}
      </Typography.Text>
      <MoveButtons
        key={selectedNodeId ?? 'none'}
        region={region}
        editable={editable}
        selectedNodeId={selectedNodeId}
        onMove={onMove}
        onMoveTo={onMoveTo}
      />
      <Button
        disabled={!editable || !selectedNodeId}
        onClick={() => {
          if (selectedNodeId) onInsert(insertRegionDelayAfter(region, selectedNodeId))
        }}
      >
        在后面插入等待
      </Button>
      <NestedControlButtons
        role={region.role}
        editable={editable}
        selectedNodeId={selectedNodeId}
        available={canInsertControl}
        controlKind={controlKind}
        onSelectControlKind={onSelectControlKind}
        onInsertControl={onInsertControl}
      />
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

function NestedControlButtons({
  role,
  editable,
  selectedNodeId,
  available,
  controlKind,
  onSelectControlKind,
  onInsertControl,
}: {
  role: string
  editable: boolean
  selectedNodeId: string | null
  available: boolean
  controlKind: ControlBlockKind
  onSelectControlKind: (kind: ControlBlockKind) => void
  onInsertControl: () => void
}) {
  if (!available) return null
  const disabled = !editable || !selectedNodeId
  return (
    <>
      <Select
        aria-label={`${role} 待插入控制块`}
        value={controlKind}
        disabled={disabled}
        options={nestedControlOptions}
        onChange={onSelectControlKind}
        style={{ minWidth: 160 }}
      />
      <Button disabled={disabled} onClick={onInsertControl}>
        在后面插入控制块
      </Button>
    </>
  )
}

const nestedControlOptions: { value: ControlBlockKind; label: string }[] = [
  { value: 'group', label: '步骤组' },
  { value: 'if', label: '条件判断' },
  { value: 'switch', label: '多分支判断' },
  { value: 'foreach', label: '集合遍历' },
  { value: 'repeat', label: '重复次数' },
  { value: 'while', label: '条件循环' },
  { value: 'do_while', label: '先执行后判断' },
  { value: 'until', label: '直到满足条件' },
  { value: 'parallel', label: '并行执行' },
  { value: 'try', label: '异常处理' },
  { value: 'fail', label: '主动失败' },
  { value: 'return', label: '返回调用方' },
]

function MoveButtons({
  region,
  editable,
  selectedNodeId,
  onMove,
  onMoveTo,
}: {
  region: WorkflowRegion
  editable: boolean
  selectedNodeId: string | null
  onMove: (direction: -1 | 1) => void
  onMoveTo: (targetIndex: number) => void
}) {
  const [targetIndex, setTargetIndex] = useState<number | undefined>()
  const disabled = !editable || !selectedNodeId
  const path = linearRegionPath(region) ?? []
  return (
    <>
      <Button disabled={disabled} onClick={() => onMove(-1)}>
        向前移动
      </Button>
      <Button disabled={disabled} onClick={() => onMove(1)}>
        向后移动
      </Button>
      {path.length > 2 && (
        <>
          <Select
            aria-label="移动步骤到位置"
            value={targetIndex}
            disabled={disabled}
            placeholder="选择执行顺序"
            options={path.map((id, index) => ({
              value: index,
              label: `第 ${index + 1} 位 · ${region.nodes.find((node) => node.id === id)?.name ?? id}`,
              disabled: id === selectedNodeId,
            }))}
            onChange={setTargetIndex}
            style={{ minWidth: 180 }}
          />
          <Button
            disabled={disabled || targetIndex === undefined}
            onClick={() => onMoveTo(targetIndex!)}
          >
            移动到指定位置
          </Button>
        </>
      )}
    </>
  )
}

function regionCanvasKey(region: WorkflowRegion): string {
  return JSON.stringify([
    region.nodes.map((node) => [node.id, node.name, node.position]),
    region.edges.map((edge) => [edge.id, edge.source, edge.target]),
  ])
}
