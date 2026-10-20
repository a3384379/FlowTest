import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Descriptions, Drawer, Input, Space, Table, Typography } from 'antd'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import { apiClient, type AuditLog } from '../../lib/api'
import { listProjectAuditLogs } from './project-service'
import { projectPath } from './project-routing'

export default function ProjectAuditPanel({
  projectId,
  canRead,
}: {
  projectId: string
  canRead: boolean
}) {
  const [params, setParams] = useSearchParams()
  const [selected, setSelected] = useState<AuditLog | null>(null)
  const { page, action, valid, query } = useAuditLogQuery(projectId, params)
  function navigate(nextPage: number, nextAction: string) {
    const next = new URLSearchParams(params)
    next.set('auditPage', String(nextPage))
    if (nextAction) next.set('auditAction', nextAction)
    else next.delete('auditAction')
    setSelected(null)
    setParams(next)
  }
  return (
    <Card title="审计日志">
      <Space orientation="vertical" className="full-width">
        <Input.Search
          key={action}
          aria-label="筛选审计动作"
          placeholder="输入完整动作名称，如 api.updated"
          defaultValue={action}
          maxLength={100}
          allowClear
          enterButton="筛选"
          onSearch={(value) => navigate(1, value.trim())}
        />
        {!valid && <Alert type="error" title="审计链接中的页码或动作筛选无效，请重新筛选。" />}
        <QueryFailureNotice queries={[query]} />
        <Table<AuditLog>
          rowKey="id"
          size="small"
          scroll={{ x: 1000 }}
          loading={query.isFetching}
          dataSource={query.data?.items ?? []}
          locale={{ emptyText: query.isError ? '审计日志读取失败，请重试' : '无审计记录' }}
          pagination={{
            current: valid ? page : 1,
            pageSize: 50,
            total: query.data?.total ?? 0,
            showSizeChanger: false,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (value) => navigate(value, action),
          }}
          columns={[
            { title: '时间', dataIndex: 'created_at', render: formatTime },
            { title: '操作者', render: (_, item) => <ActorSummary item={item} /> },
            { title: '操作', dataIndex: 'action' },
            { title: '资源', render: (_, item) => <ResourceSummary item={item} /> },
            { title: 'Trace ID', render: (_, item) => <CopyValue value={traceId(item)} /> },
            {
              title: '详情',
              render: (_, item) => (
                <Button type="link" onClick={() => setSelected(item)}>
                  查看详情
                </Button>
              ),
            },
          ]}
        />
      </Space>
      {selected && (
        <AuditDetails
          key={selected.id}
          item={selected}
          projectId={projectId}
          canRead={canRead && query.isSuccess}
          onClose={() => setSelected(null)}
        />
      )}
    </Card>
  )
}

function useAuditLogQuery(projectId: string, params: URLSearchParams) {
  const rawPage = params.get('auditPage') ?? '1'
  const action = params.get('auditAction') ?? ''
  const page = Number(rawPage)
  const valid = /^[1-9]\d*$/.test(rawPage) && Number.isSafeInteger(page) && action.length <= 100
  const query = useQuery({
    queryKey: ['project-audit', projectId, page, action],
    queryFn: () => listProjectAuditLogs(projectId, page, action),
    enabled: valid,
  })
  return { page, action, valid, query }
}

function ActorSummary({ item }: { item: AuditLog }) {
  return (
    <Space orientation="vertical" size={0}>
      <span title="当前显示名，历史操作者以用户 ID 为准">
        {item.actor_display_name || '未提供'}
      </span>
      {item.actor_user_id && (
        <Typography.Text type="secondary">{item.actor_user_id}</Typography.Text>
      )}
    </Space>
  )
}

function ResourceSummary({ item }: { item: AuditLog }) {
  const name = typeof item.details.name === 'string' ? item.details.name : undefined
  return (
    <Space orientation="vertical" size={0}>
      <span>{name || item.resource_type}</span>
      <Typography.Text type="secondary">{item.resource_id || '未提供'}</Typography.Text>
    </Space>
  )
}

function AuditDetails({
  item,
  projectId,
  canRead,
  onClose,
}: {
  item: AuditLog
  projectId: string
  canRead: boolean
  onClose: () => void
}) {
  return (
    <Drawer title="审计记录详情" open onClose={onClose} size={640}>
      <Descriptions
        column={1}
        bordered
        items={[
          { key: 'id', label: '记录 ID', children: <CopyValue value={item.id} /> },
          { key: 'time', label: '时间', children: formatTime(item.created_at) },
          {
            key: 'actor',
            label: '操作者当前显示名',
            children: item.actor_display_name || '未提供',
          },
          {
            key: 'actorId',
            label: '操作者 ID',
            children: <CopyValue value={item.actor_user_id} />,
          },
          { key: 'action', label: '动作', children: item.action },
          { key: 'resourceType', label: '资源类型', children: item.resource_type },
          { key: 'resourceId', label: '资源 ID', children: <CopyValue value={item.resource_id} /> },
          { key: 'trace', label: 'Trace ID', children: <CopyValue value={traceId(item)} /> },
        ]}
      />
      <AuditResourceLink item={item} projectId={projectId} canRead={canRead} onNavigate={onClose} />
      <Typography.Title level={5}>变更内容（只读）</Typography.Title>
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
        {JSON.stringify(item.details, null, 2)}
      </pre>
    </Drawer>
  )
}

function AuditResourceLink({
  item,
  projectId,
  canRead,
  onNavigate,
}: {
  item: AuditLog
  projectId: string
  canRead: boolean
  onNavigate: () => void
}) {
  const target = auditResource(item, projectId)
  const query = useQuery({
    queryKey: ['audit-resource-access', projectId, item.resource_type, item.resource_id],
    queryFn: async () => (await apiClient.get(target!.api)).data as unknown,
    enabled: canRead && Boolean(target),
    retry: false,
  })
  if (!canRead || !target) return null
  if (query.isError) return <QueryFailureNotice queries={[query]} />
  return query.isSuccess && !query.isFetching ? (
    <Link to={target.path} onClick={onNavigate}>
      定位资源
    </Link>
  ) : (
    <span>正在确认资源访问权限…</span>
  )
}

function auditResource(item: AuditLog, projectId: string): { api: string; path: string } | null {
  if (item.project_id !== projectId || !item.resource_id) return null
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(item.resource_id))
    return null
  const id = encodeURIComponent(item.resource_id)
  const base = `/projects/${encodeURIComponent(projectId)}`
  switch (item.resource_type) {
    case 'api_definition':
      return { api: `${base}/apis/${id}`, path: `${projectPath(projectId, 'apis')}?focus=${id}` }
    case 'workflow':
      return {
        api: `${base}/workflows/${id}`,
        path: `${projectPath(projectId, 'workflows')}?focus=${id}`,
      }
    case 'workflow_execution':
      return {
        api: `${base}/reports/executions/${id}`,
        path: `${projectPath(projectId, 'reports')}?execution=${id}`,
      }
    case 'project':
      return item.resource_id === projectId
        ? { api: base, path: projectPath(projectId, 'settings') }
        : null
    default:
      return null
  }
}

function CopyValue({ value }: { value: string | null | undefined }) {
  return value ? <Typography.Text copyable>{value}</Typography.Text> : <span>未提供</span>
}

function traceId(item: AuditLog): string | undefined {
  return typeof item.details.trace_id === 'string' ? item.details.trace_id : undefined
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN')
}
