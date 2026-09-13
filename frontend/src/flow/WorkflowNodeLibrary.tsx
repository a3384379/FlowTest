import { Alert, Button, Collapse, Drawer, Empty, Input, Typography } from 'antd'
import { useState, type ReactNode } from 'react'
export type NodeLibraryGroup = { name: string; keywords: string; content: ReactNode }
export default function WorkflowNodeLibrary({
  open,
  onClose,
  groups,
  unavailable,
}: {
  open: boolean
  onClose: () => void
  groups: NodeLibraryGroup[]
  unavailable: string[]
}) {
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<string[]>(['接口请求', '控制与校验'])
  const visible = groups.filter((group) =>
    `${group.name} ${group.keywords}`.toLowerCase().includes(query.trim().toLowerCase()),
  )
  return (
    <Drawer title="添加节点" open={open} onClose={onClose} size={320} mask={false}>
      <Input.Search
        aria-label="搜索节点类型"
        placeholder="搜索名称、协议或用途"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        allowClear
      />
      <Typography.Paragraph type="secondary">
        点击添加，或将节点拖到画布。资源节点需先选择相应资源。
      </Typography.Paragraph>
      {unavailable.length > 0 && (
        <Alert type="info" title="部分节点暂不可用" description={unavailable.join('；')} />
      )}
      {visible.length === 0 && <Empty description="没有匹配的节点类型" />}
      <Collapse
        activeKey={query ? visible.map((group) => group.name) : expanded}
        onChange={setExpanded}
        items={visible.map((group) => ({
          key: group.name,
          label: group.name,
          children: <div className="workflow-library-group">{group.content}</div>,
        }))}
      />
      <Button block onClick={onClose}>
        返回画布
      </Button>
    </Drawer>
  )
}
