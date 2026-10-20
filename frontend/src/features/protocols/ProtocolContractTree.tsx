import { DownOutlined, RightOutlined } from '@ant-design/icons'
import { Button, Empty, Pagination, Space, Spin, Tag, Typography } from 'antd'
import { useState } from 'react'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import type { ProtocolStructureEntry, SchemaArtifact } from './protocol-service'
import { useProtocolStructure } from './use-protocol-structure'

type TreeProps = {
  asset: SchemaArtifact
  onSelect: (path: { key: string; label: string }, ancestors: readonly string[]) => void
}
export default function ProtocolContractTree({
  asset,
  onSelect,
  enabled,
}: TreeProps & { enabled: boolean }) {
  return (
    <div aria-label="契约结构树" className="protocol-contract-tree">
      <TreePage asset={asset} node="root" path={['root']} enabled={enabled} onSelect={onSelect} />
    </div>
  )
}
function TreePage({
  asset,
  node,
  path,
  onSelect,
  enabled,
}: TreeProps & { node: string; path: string[]; enabled: boolean }) {
  const [page, setPage] = useState(1)
  const query = useProtocolStructure(asset, node, page, enabled)
  return (
    <>
      <QueryFailureNotice queries={[query]} />
      {query.data?.view.notice && (
        <Typography.Paragraph type="secondary">{query.data.view.notice}</Typography.Paragraph>
      )}
      {query.isPending && <Spin aria-label="加载契约分支" />}
      {query.data && !query.isError && (
        <TreeLevel
          asset={asset}
          entries={query.data.view.entries}
          path={path}
          onSelect={onSelect}
        />
      )}
      <Pagination
        current={page}
        total={query.data?.view.total ?? 0}
        pageSize={25}
        onChange={setPage}
        size="small"
        showSizeChanger={false}
        hideOnSinglePage
      />
    </>
  )
}
function TreeLevel({
  asset,
  entries,
  path,
  onSelect,
}: TreeProps & { entries: ProtocolStructureEntry[]; path: string[] }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  if (!entries.length)
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有子字段" />
  return (
    <ul className="protocol-contract-branches">
      {entries.map((entry, index) => {
        const id = `${entry.key}:${index}`
        const expandable = entry.expandable && path.length < 9 && !path.includes(entry.key)
        const open = expanded === id
        return (
          <TreeBranch
            key={id}
            asset={asset}
            entry={entry}
            path={path}
            open={open}
            expandable={expandable}
            onToggle={() => setExpanded(open ? null : id)}
            onSelect={onSelect}
          />
        )
      })}
    </ul>
  )
}

function TreeBranch({
  asset,
  entry,
  path,
  open,
  expandable,
  onToggle,
  onSelect,
}: TreeProps & {
  entry: ProtocolStructureEntry
  path: string[]
  open: boolean
  expandable: boolean
  onToggle: () => void
}) {
  return (
    <li>
      <TreeBranchHeader
        entry={entry}
        open={open}
        expandable={expandable}
        onToggle={onToggle}
        onSelect={() => onSelect({ key: entry.key, label: entry.label }, path)}
      />
      {entry.type_label && (
        <Typography.Paragraph type="secondary" className="protocol-contract-type">
          {entry.type_label}
        </Typography.Paragraph>
      )}
      {open && expandable && (
        <TreePage
          asset={asset}
          node={entry.key}
          path={[...path, entry.key]}
          onSelect={onSelect}
          enabled
        />
      )}
    </li>
  )
}
function TreeBranchHeader({
  entry,
  open,
  expandable,
  onToggle,
  onSelect,
}: {
  entry: ProtocolStructureEntry
  open: boolean
  expandable: boolean
  onToggle: () => void
  onSelect: () => void
}) {
  return (
    <Space wrap size={4}>
      {entry.expandable && (
        <Button
          type="text"
          size="small"
          aria-label={`${open ? '收起' : '展开'}契约${entry.label}`}
          disabled={!expandable}
          icon={open ? <DownOutlined /> : <RightOutlined />}
          onClick={onToggle}
        />
      )}
      {entry.expandable ? (
        <Button type="link" aria-label={`查看契约${entry.label}`} onClick={onSelect}>
          {entry.label}
        </Button>
      ) : (
        <Typography.Text>{entry.label}</Typography.Text>
      )}
      {entry.required && <Tag color="orange">必填</Tag>}
      {entry.expandable && !expandable && <Tag>引用或层级上限</Tag>}
    </Space>
  )
}
