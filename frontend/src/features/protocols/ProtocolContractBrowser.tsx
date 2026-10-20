import { useQuery } from '@tanstack/react-query'
import { Button, Collapse, Empty, Pagination, Space, Spin, Tag, Typography } from 'antd'
import { useState } from 'react'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import {
  inspectProtocolStructure,
  type ProtocolInputExample,
  type ProtocolStructureEntry,
  type ProtocolStructureResponse,
  type SchemaArtifact,
} from './protocol-service'

type Path = { key: string; label: string }
export default function ProtocolContractBrowser({
  asset,
  onExample,
  initialNode = 'root',
}: {
  asset: SchemaArtifact
  initialNode?: string
  onExample: (example: ProtocolInputExample) => void
}) {
  const [paths, setPaths] = useState<Path[]>(
    initialNode === 'root'
      ? [{ key: 'root', label: '契约结构' }]
      : [
          { key: 'root', label: '契约结构' },
          { key: initialNode, label: '定位契约字段/方法' },
        ],
  )
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState(true)
  const current = paths[paths.length - 1]
  const structure = useQuery({
    queryKey: [
      'protocol-structure',
      asset.project_id,
      asset.protocol,
      asset.id,
      asset.version,
      asset.content_sha256,
      current.key,
      page,
    ],
    queryFn: () => inspectProtocolStructure(asset, current.key, page),
    enabled: open,
    staleTime: Infinity,
    retry: false,
  })
  function navigate(path: Path) {
    setPaths((values) => [...values, path])
    setPage(1)
  }
  const content = (
    <>
      <Space wrap>
        <Button
          disabled={paths.length === 1}
          onClick={() => {
            setPaths((values) => values.slice(0, -1))
            setPage(1)
          }}
        >
          返回上层
        </Button>
        <Button
          onClick={() => {
            setPaths([{ key: 'root', label: '契约结构' }])
            setPage(1)
          }}
        >
          结构首页
        </Button>
        <Button
          onClick={() => navigate({ key: 'source', label: '导入源文档' })}
          disabled={current.key === 'source'}
        >
          查看源文档
        </Button>
      </Space>
      <Typography.Paragraph className="protocol-contract-path">
        {paths.map((path) => path.label).join(' / ')}
      </Typography.Paragraph>
      <QueryFailureNotice queries={[structure]} />
      {structure.isPending && <Spin aria-label="加载契约结构" />}
      {structure.data && !structure.isError && (
        <ContractView data={structure.data.view} navigate={navigate} onExample={onExample} />
      )}
      <Pagination
        size="small"
        current={page}
        pageSize={25}
        total={structure.data?.view.total ?? 0}
        onChange={setPage}
        showSizeChanger={false}
        hideOnSinglePage
      />
    </>
  )
  return (
    <Collapse
      activeKey={open ? ['contract'] : []}
      onChange={(keys) => setOpen(keys.includes('contract'))}
      items={[{ key: 'contract', label: '契约结构与输入引导', children: content }]}
    />
  )
}
function ContractView({
  data,
  navigate,
  onExample,
}: {
  data: ProtocolStructureResponse['view']
  navigate: (path: Path) => void
  onExample: (example: ProtocolInputExample) => void
}) {
  return (
    <div className="protocol-contract-view">
      <Typography.Text strong>{data.label}</Typography.Text>
      {data.notice && <Typography.Paragraph type="secondary">{data.notice}</Typography.Paragraph>}
      {data.document !== null ? (
        <>
          <Tag>源文档 · {data.document_format}</Tag>
          <pre className="protocol-result protocol-contract-source">{data.document}</pre>
        </>
      ) : (
        <>
          {data.entries.length === 0 && (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该节点没有子字段" />
          )}
          <ul className="protocol-contract-fields">
            {data.entries.map((entry, index) => (
              <ContractField
                key={`${entry.key}:${entry.label}:${index}`}
                entry={entry}
                navigate={navigate}
              />
            ))}
          </ul>
        </>
      )}
      {data.example && <Button onClick={() => onExample(data.example!)}>将样例填入请求草稿</Button>}
    </div>
  )
}
function ContractField({
  entry,
  navigate,
}: {
  entry: ProtocolStructureEntry
  navigate: (path: Path) => void
}) {
  return (
    <li>
      <Space wrap>
        {entry.expandable ? (
          <Button type="link" onClick={() => navigate({ key: entry.key, label: entry.label })}>
            {entry.label}
          </Button>
        ) : (
          <Typography.Text>{entry.label}</Typography.Text>
        )}
        {entry.required && <Tag color="orange">必填</Tag>}
      </Space>
      {entry.type_label && <Typography.Paragraph code>{entry.type_label}</Typography.Paragraph>}
      {entry.description && (
        <Typography.Paragraph type="secondary">{entry.description}</Typography.Paragraph>
      )}
    </li>
  )
}
