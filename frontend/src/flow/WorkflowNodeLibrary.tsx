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
import { Button, Drawer, Empty, Input, Tag, Tooltip, Typography } from 'antd'
import { useMemo, useState, useSyncExternalStore, type DragEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import {
  nodeLibraryCategories,
  type NodeIconKey,
  type NodeRegistryItem,
} from './editor/node-registry'

export type NodeLibraryItem = NodeRegistryItem & {
  disabled: boolean
  unavailableReason?: string
  resourceControl?: ReactNode
  configurationAction?: ReactNode
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
  docked = false,
  dockContainer,
}: {
  open: boolean
  onClose: () => void
  items: NodeLibraryItem[]
  docked?: boolean
  dockContainer?: HTMLElement | null
}) {
  const wide = useSyncExternalStore(subscribeLibraryViewport, libraryViewport)
  const inline = docked && wide && !open && Boolean(dockContainer)
  const [query, setQuery] = useState('')
  const [activeCategory, setActiveCategory] =
    useState<(typeof nodeLibraryCategories)[number]>('接口/协议')
  const normalizedQuery = query.trim().toLowerCase()
  const visible = useMemo(
    () =>
      items.filter((item) => {
        if (!normalizedQuery) return inline || item.category === activeCategory
        return `${item.category} ${item.label} ${item.description} ${item.keywords} ${item.prerequisite ?? ''}`
          .toLowerCase()
          .includes(normalizedQuery)
      }),
    [activeCategory, items, normalizedQuery, inline],
  )

  if (inline && dockContainer)
    return createPortal(
      <aside className="workflow-node-library-docked" aria-label="节点库">
        <header>
          <strong>节点库</strong>
          <Tag>{items.length}</Tag>
        </header>
        <Input.Search
          aria-label="搜索节点类型"
          placeholder="搜索名称或类型"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          allowClear
        />
        <div className="workflow-library-inline-results">
          {nodeLibraryCategories.map((category) => {
            const matches = visible.filter((item) => item.category === category)
            if (!matches.length) return null
            return (
              <section key={category}>
                <h3>{category}</h3>
                {matches.map((item) => (
                  <NodeLibraryRow key={item.id} item={item} />
                ))}
              </section>
            )
          })}
          {!visible.length && (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的节点类型" />
          )}
        </div>
        <Typography.Text type="secondary">点击添加或拖入画布</Typography.Text>
      </aside>,
      dockContainer,
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

function subscribeLibraryViewport(listener: () => void): () => void {
  const media = window.matchMedia('(min-width: 1360px)')
  media.addEventListener('change', listener)
  return () => media.removeEventListener('change', listener)
}
function libraryViewport(): boolean {
  return window.matchMedia('(min-width: 1360px)').matches
}

function NodeLibraryRow({ item }: { item: NodeLibraryItem }) {
  return (
    <div className="workflow-library-row" draggable={!item.disabled} onDragStart={item.onDragStart}>
      <Tooltip title={item.unavailableReason ?? item.description}>
        <span>
          <Button
            type="text"
            block
            disabled={item.disabled}
            aria-label={`添加${item.label}`}
            icon={nodeIcons[item.icon]}
            onClick={item.onAdd}
          >
            {item.label}
          </Button>
        </span>
      </Tooltip>
      {item.resourceControl && (
        <details>
          <summary>选择资源</summary>
          {item.resourceControl}
        </details>
      )}
      {item.configurationAction}
    </div>
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
      {item.configurationAction && (
        <div className="workflow-library-configuration-action">{item.configurationAction}</div>
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
