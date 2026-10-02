import { HistoryOutlined } from '@ant-design/icons'
import { Button, Drawer, Empty, Tag, Typography } from 'antd'
import { useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import type { WorkflowDefinition, WorkflowNode, WorkflowNodeExecution } from '../lib/api'

type TrajectoryProps = {
  mode: 'run' | 'history'
  executionId?: string
  definition: WorkflowDefinition
  nodes: WorkflowNodeExecution[]
  selectedId: string | null
  dockContainer: HTMLElement | null
  docked: boolean
  onSelect: (nodeId: string) => void
}

export default function WorkflowRunTrajectory(props: TrajectoryProps) {
  const [open, setOpen] = useState(false)
  const wide = useSyncExternalStore(subscribeViewport, wideViewport)
  const content = (
    <TrajectoryContent
      {...props}
      onSelect={(nodeId) => {
        props.onSelect(nodeId)
        setOpen(false)
      }}
    />
  )
  const inline = props.docked && wide && Boolean(props.dockContainer)
  return (
    <>
      {!inline && (
        <Button aria-label="执行轨迹" icon={<HistoryOutlined />} onClick={() => setOpen(true)}>
          执行轨迹
        </Button>
      )}
      {inline && props.dockContainer && createPortal(content, props.dockContainer)}
      <Drawer
        title="执行轨迹"
        open={open}
        onClose={() => setOpen(false)}
        size={300}
        placement="left"
      >
        {!inline && content}
      </Drawer>
    </>
  )
}

function TrajectoryContent({
  mode,
  executionId,
  definition,
  nodes,
  selectedId,
  onSelect,
}: TrajectoryProps) {
  const byId = new Map(nodes.map((node) => [node.node_id, node]))
  return (
    <aside className="workflow-run-trajectory" aria-label="执行轨迹">
      <header>
        <strong>执行轨迹</strong>
        <Tag>{definition.nodes.length}</Tag>
      </header>
      <Typography.Text type="secondary">
        {executionId ? executionId.slice(0, 8) : '等待执行记录'} ·{' '}
        {mode === 'history' ? '历史只读' : '运行中视图'}
      </Typography.Text>
      <nav>
        {definition.nodes.map((node) => (
          <TrajectoryNode
            key={node.id}
            node={node}
            execution={byId.get(node.id)}
            selected={node.id === selectedId}
            onSelect={onSelect}
          />
        ))}
      </nav>
      {!definition.nodes.length && (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂未提供执行快照" />
      )}
      <Typography.Text type="secondary">选择节点定位画布，查看当次证据。</Typography.Text>
    </aside>
  )
}

function TrajectoryNode({
  node,
  execution,
  selected,
  onSelect,
}: {
  node: WorkflowNode
  execution?: WorkflowNodeExecution
  selected: boolean
  onSelect: (nodeId: string) => void
}) {
  const labels: Readonly<Record<string, string>> = {
    pending: '待执行',
    running: '执行中',
    passed: '通过',
    failed: '失败',
    skipped: '已跳过',
    cancelled: '已取消',
  }
  const status = execution?.status
  const duration = execution?.result?.observations?.at(-1)?.duration_ms
  return (
    <button
      type="button"
      className={`workflow-trajectory-node is-${status ?? 'unknown'}`}
      aria-pressed={selected}
      onClick={() => onSelect(node.id)}
    >
      <strong>{node.name}</strong>
      <span>
        {status ? (labels[status] ?? status) : '未提供节点记录'}
        {duration !== undefined ? ` · ${duration} ms` : ''}
      </span>
    </button>
  )
}

function subscribeViewport(listener: () => void): () => void {
  const media = window.matchMedia('(min-width: 1360px)')
  media.addEventListener('change', listener)
  return () => media.removeEventListener('change', listener)
}
function wideViewport(): boolean {
  return window.matchMedia('(min-width: 1360px)').matches
}
