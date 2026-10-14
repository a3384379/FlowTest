import {
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  NodeIndexOutlined,
} from '@ant-design/icons'
import { EdgeToolbar, NodeToolbar, Position } from '@xyflow/react'
import { Button, Space, Tag } from 'antd'
import type { MouseEvent, PointerEvent } from 'react'

type ActionProps = {
  onConfigure: () => void
  onDelete: () => void
  editable: boolean
}

export type NodeInspectionMode = 'configuration' | 'execution'

function stopCanvasEvent(event: MouseEvent | PointerEvent) {
  event.stopPropagation()
}

export function WorkflowNodeActions({
  visible,
  inspectionMode,
  canCopy,
  onCopy,
  ...actions
}: ActionProps & {
  visible: boolean
  inspectionMode: NodeInspectionMode
  canCopy: boolean
  onCopy: () => void
}) {
  const inspectionLabel = inspectionMode === 'execution' ? '查看运行结果' : '查看配置'
  return (
    <NodeToolbar
      isVisible={visible}
      position={Position.Top}
      offset={12}
      className="workflow-selection-toolbar nodrag nopan"
      aria-label="节点快捷操作"
      onPointerDown={stopCanvasEvent}
      onClick={stopCanvasEvent}
    >
      <Space.Compact>
        <Button
          size="small"
          icon={<EyeOutlined />}
          aria-label={inspectionLabel}
          onClick={actions.onConfigure}
        >
          {inspectionLabel}
        </Button>
        <Button size="small" icon={<CopyOutlined />} disabled={!canCopy} onClick={onCopy}>
          复制
        </Button>
        <Button
          size="small"
          danger
          icon={<DeleteOutlined />}
          disabled={!actions.editable}
          onClick={actions.onDelete}
        >
          删除
        </Button>
      </Space.Compact>
    </NodeToolbar>
  )
}

export function WorkflowEdgeActions({
  edgeId,
  x,
  y,
  visible,
  branch,
  ...actions
}: ActionProps & {
  edgeId: string
  x: number
  y: number
  visible: boolean
  branch: 'true' | 'false' | null
}) {
  return (
    <EdgeToolbar
      edgeId={edgeId}
      x={x}
      y={y - 44}
      isVisible={visible}
      className="workflow-selection-toolbar workflow-edge-toolbar nodrag nopan"
      aria-label="连线快捷操作"
      onPointerDown={stopCanvasEvent}
      onClick={stopCanvasEvent}
    >
      <Space.Compact>
        {branch && (
          <Tag icon={<NodeIndexOutlined />} color={branch === 'true' ? 'green' : 'volcano'}>
            {branch === 'true' ? '是分支' : '否分支'}
          </Tag>
        )}
        <Button size="small" icon={<EditOutlined />} onClick={actions.onConfigure}>
          映射
        </Button>
        <Button
          size="small"
          danger
          icon={<DeleteOutlined />}
          disabled={!actions.editable}
          onClick={actions.onDelete}
        >
          删除连线
        </Button>
      </Space.Compact>
    </EdgeToolbar>
  )
}
