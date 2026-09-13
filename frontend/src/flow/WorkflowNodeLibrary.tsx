import {
  ApiOutlined,
  ApartmentOutlined,
  BranchesOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  FlagOutlined,
  PlusOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { Button, Drawer, Empty, Input, Tag, Typography } from 'antd'
import { useMemo, useState, type DragEvent, type ReactNode } from 'react'
import {
  nodeLibraryCategories,
  type NodeIconKey,
  type NodeRegistryItem,
} from './editor/node-registry'

export type NodeLibraryItem = NodeRegistryItem & {
  disabled: boolean
  unavailableReason?: string
  resourceControl?: ReactNode
  onAdd: () => void
  onDragStart: (event: DragEvent<HTMLElement>) => void
}

const nodeIcons: Record<NodeIconKey, ReactNode> = {
  api: <ApiOutlined />,
  control: <BranchesOutlined />,
  data: <DatabaseOutlined />,
  flow: <ApartmentOutlined />,
  timer: <ClockCircleOutlined />,
  end: <FlagOutlined />,
}

export default function WorkflowNodeLibrary({
  open,
  onClose,
  items,
}: {
  open: boolean
  onClose: () => void
  items: NodeLibraryItem[]
}) {
  const [query, setQuery] = useState('')
  const [activeCategory, setActiveCategory] =
    useState<(typeof nodeLibraryCategories)[number]>('接口/协议')
  const normalizedQuery = query.trim().toLowerCase()
  const visible = useMemo(
    () =>
      items.filter((item) => {
        if (!normalizedQuery) return item.category === activeCategory
        return `${item.category} ${item.label} ${item.description} ${item.keywords} ${item.prerequisite ?? ''}`
          .toLowerCase()
          .includes(normalizedQuery)
      }),
    [activeCategory, items, normalizedQuery],
  )

  return (
    <Drawer
      title="添加节点"
      open={open}
      onClose={onClose}
      size={400}
      placement="left"
      mask={false}
      rootClassName="workflow-node-library"
    >
      <Input.Search
        aria-label="搜索节点类型"
        placeholder="搜索名称、协议或用途"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        allowClear
      />
      <Typography.Paragraph type="secondary" className="workflow-library-hint">
        点击添加或拖到画布；资源依赖会在对应节点中说明。
      </Typography.Paragraph>
      <div className="workflow-library-catalog">
        {!normalizedQuery && (
          <nav className="workflow-library-categories" aria-label="节点分类">
            {nodeLibraryCategories.map((category) => (
              <Button
                key={category}
                type={activeCategory === category ? 'primary' : 'text'}
                onClick={() => setActiveCategory(category)}
              >
                {category}
              </Button>
            ))}
          </nav>
        )}
        <div className="workflow-library-results" aria-live="polite">
          {visible.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的节点类型" />
          ) : (
            visible.map((item) => <NodeLibraryCard key={item.id} item={item} />)
          )}
        </div>
      </div>
      <div className="workflow-library-footer">
        <Button block onClick={onClose}>
          返回画布
        </Button>
      </div>
    </Drawer>
  )
}

function NodeLibraryCard({ item }: { item: NodeLibraryItem }) {
  return (
    <article
      className={`workflow-library-card${item.disabled ? ' is-disabled' : ''}`}
      draggable={!item.disabled}
      onDragStart={item.onDragStart}
    >
      <div className="workflow-library-card-main">
        <span className="workflow-library-card-icon">{nodeIcons[item.icon]}</span>
        <div className="workflow-library-card-copy">
          <div className="workflow-library-card-title">
            <Typography.Text strong>{item.label}</Typography.Text>
            <Tag color={item.disabled ? 'default' : 'success'}>
              {item.disabled ? '不可用' : '可添加'}
            </Tag>
          </div>
          <Typography.Text type="secondary">{item.description}</Typography.Text>
        </div>
      </div>
      {item.resourceControl && (
        <div className="workflow-library-resource-control">{item.resourceControl}</div>
      )}
      {item.unavailableReason && (
        <div className="workflow-library-card-reason">
          <WarningOutlined />
          <span>{item.unavailableReason}</span>
        </div>
      )}
      <Button
        block
        type={item.disabled ? 'default' : 'primary'}
        icon={<PlusOutlined />}
        disabled={item.disabled}
        onClick={item.onAdd}
      >
        添加{item.label}
      </Button>
    </article>
  )
}
