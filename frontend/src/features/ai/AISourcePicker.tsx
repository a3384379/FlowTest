import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Input, Pagination, Select, Space, Table, Typography } from 'antd'
import { useState } from 'react'
import { apiErrorWithTrace } from '../../lib/api'
import {
  getAISource,
  listAISources,
  type AIPublicSource,
  type AISourceKind,
  type AISourceSummary,
} from './ai-service'

export default function AISourcePicker({
  projectId,
  onUse,
  initialKind,
}: {
  projectId: string
  initialKind: AISourceKind
  onUse: (source: AIPublicSource) => void
}) {
  const [kind, setKind] = useState<AISourceKind>(initialKind)
  const [page, setPage] = useState(1),
    [search, setSearch] = useState(''),
    [exactId, setExactId] = useState(''),
    [searchDraft, setSearchDraft] = useState('')
  const [selection, setSelection] = useState<{ id: string; version?: number } | null>(null)
  const sources = useQuery({
    queryKey: ['ai-public-sources', projectId, kind, page, search],
    queryFn: () => listAISources(projectId, kind, page, search),
  })
  const detail = useQuery({
    queryKey: ['ai-public-source', projectId, kind, selection],
    queryFn: () => getAISource(projectId, kind, selection!.id, selection?.version),
    enabled: Boolean(selection),
  })
  const error = sources.error ?? detail.error
  return (
    <Card size="small" title="选择公开来源">
      <Typography.Paragraph type="secondary">
        只读取公开契约或冻结执行的身份、状态和错误摘要。不会读取认证、请求头、变量或响应正文。
      </Typography.Paragraph>
      <Space wrap>
        <Select
          aria-label="来源类型"
          value={kind}
          onChange={(value) => {
            setKind(value)
            setPage(1)
            setSelection(null)
            setSearch('')
            setSearchDraft('')
          }}
          options={[
            { value: 'api', label: '接口契约' },
            { value: 'schema', label: '协议 Schema' },
            { value: 'execution', label: '冻结执行' },
          ]}
        />
        <Input.Search
          aria-label="搜索公开来源"
          placeholder={kind === 'execution' ? '执行ID或状态' : '来源名称'}
          allowClear
          value={searchDraft}
          onChange={(event) => setSearchDraft(event.target.value)}
          onSearch={(value) => {
            setSearchDraft(value.trim())
            setSearch(value.trim())
            setPage(1)
          }}
        />
      </Space>
      {error ? (
        <Alert
          showIcon
          type="error"
          title="公开来源读取失败"
          description={apiErrorWithTrace(error)}
          action={
            <Button
              onClick={() => {
                if (sources.isError) void sources.refetch()
                if (detail.isError) void detail.refetch()
              }}
            >
              重试来源
            </Button>
          }
        />
      ) : null}
      <Table<AISourceSummary>
        size="small"
        rowKey="id"
        loading={sources.isLoading}
        pagination={false}
        scroll={{ x: 450 }}
        dataSource={sources.isSuccess ? sources.data.items : []}
        columns={[
          { title: '来源', dataIndex: 'name' },
          {
            title: '版本 / 状态',
            render: (_, item) => (item.version ? `v${item.version}` : (item.status ?? '未提供')),
          },
          {
            title: '操作',
            render: (_, item) => (
              <Button
                type="link"
                onClick={() => setSelection({ id: item.id, version: item.version ?? undefined })}
              >
                查看材料
              </Button>
            ),
          },
        ]}
      />
      <Pagination
        size="small"
        current={page}
        pageSize={20}
        total={sources.isSuccess ? sources.data.total : 0}
        showSizeChanger={false}
        onChange={setPage}
      />
      <Space.Compact className="full-width">
        <Input
          aria-label="确切来源ID"
          value={exactId}
          onChange={(e) => setExactId(e.target.value)}
          placeholder="确切来源ID"
        />
        <Button disabled={!exactId.trim()} onClick={() => setSelection({ id: exactId.trim() })}>
          按ID读取
        </Button>
      </Space.Compact>
      {detail.isFetching ? <Typography.Text>正在读取固定来源…</Typography.Text> : null}
      {detail.isSuccess && !detail.isFetching ? (
        <section aria-label="公开来源材料">
          <Typography.Paragraph>
            {detail.data.metadata.name} · {detail.data.metadata.source_id} ·{' '}
            {detail.data.metadata.version
              ? `v${detail.data.metadata.version}`
              : detail.data.metadata.status}
          </Typography.Paragraph>
          {detail.data.notices.map((notice) => (
            <Alert key={notice} type="info" title={notice} />
          ))}
          <pre
            style={{
              maxHeight: 220,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              overflowWrap: 'anywhere',
            }}
          >
            {JSON.stringify(detail.data, null, 2)}
          </pre>
          <Button onClick={() => onUse(detail.data)}>使用此固定材料</Button>
        </section>
      ) : null}
    </Card>
  )
}
