import { AuditOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Space,
  Table,
  Typography,
} from 'antd'
import { useState } from 'react'

import {
  listOrganizationAuditLogs,
  type OrganizationAuditFilters,
  type OrganizationAuditLog,
} from '../features/organizations/organization-service'
import OrganizationQueryBoundary from './OrganizationQueryBoundary'

type AuditFormValues = Omit<OrganizationAuditFilters, 'page' | 'page_size'>

export default function OrganizationAuditPanel({ organizationId }: { organizationId: string }) {
  const [filters, setFilters] = useState<OrganizationAuditFilters>({ page: 1, page_size: 10 })
  const [selected, setSelected] = useState<OrganizationAuditLog | null>(null)
  const audit = useQuery({
    queryKey: ['organization-audit', organizationId, filters],
    queryFn: () => listOrganizationAuditLogs(organizationId, filters),
  })
  return (
    <Card
      title={
        <Space>
          <AuditOutlined />
          组织审计查询
        </Space>
      }
    >
      <AuditFilters
        onSearch={(values) => {
          setSelected(null)
          setFilters({ ...values, page: 1, page_size: filters.page_size })
        }}
      />
      <OrganizationQueryBoundary label="组织审计" query={audit}>
        {(page) => (
          <>
            {page.page > 1 && page.items.length === 0 && (
              <Alert
                showIcon
                type="warning"
                title="当前页已超出审计目录范围"
                description="审计记录可能已按保留策略清理，请返回首页重新查询。"
                action={
                  <Button onClick={() => setFilters({ ...filters, page: 1 })}>返回审计首页</Button>
                }
              />
            )}
            <Table
              rowKey="id"
              size="small"
              scroll={{ x: 900 }}
              dataSource={page.items}
              pagination={{
                current: page.page,
                pageSize: page.page_size,
                total: page.total,
                showSizeChanger: false,
                showTotal: (total) => `共 ${total} 条`,
                onChange: (next) => setFilters({ ...filters, page: next }),
              }}
              columns={[
                {
                  title: '时间',
                  dataIndex: 'created_at',
                  render: (value: string) =>
                    new Date(value).toLocaleString('zh-CN', { hour12: false }),
                },
                { title: '动作', dataIndex: 'action' },
                {
                  title: '操作者',
                  dataIndex: 'actor_user_id',
                  render: (value: string | null) => value ?? '系统 / 已删除用户',
                },
                { title: '资源类型', dataIndex: 'resource_type' },
                {
                  title: '资源 ID',
                  dataIndex: 'resource_id',
                  render: (value: string | null) => value ?? '未记录',
                },
                {
                  title: 'Trace ID',
                  render: (_, entry) =>
                    typeof entry.details.trace_id === 'string' ? entry.details.trace_id : '未记录',
                },
                {
                  title: '详情',
                  render: (_, entry) => (
                    <Button
                      size="small"
                      aria-label="查看审计详情"
                      onClick={() => setSelected(entry)}
                    >
                      查看
                    </Button>
                  ),
                },
              ]}
            />
          </>
        )}
      </OrganizationQueryBoundary>
      <AuditDetails
        entry={audit.isSuccess && !audit.isFetching ? selected : null}
        onClose={() => setSelected(null)}
      />
    </Card>
  )
}

function AuditFilters({ onSearch }: { onSearch: (values: AuditFormValues) => void }) {
  const [form] = Form.useForm<AuditFormValues>()
  return (
    <Form
      form={form}
      layout="inline"
      onFinish={(values) => onSearch(normalizeFilters(values))}
      style={{ marginBottom: 16, gap: 8 }}
    >
      <Form.Item name="action">
        <Input aria-label="审计动作" placeholder="动作（精确匹配）" />
      </Form.Item>
      <Form.Item name="actor_user_id">
        <Input aria-label="操作者 ID" placeholder="操作者 UUID" />
      </Form.Item>
      <Form.Item name="resource_type">
        <Input aria-label="资源类型" placeholder="资源类型（精确匹配）" />
      </Form.Item>
      <Form.Item name="resource_id">
        <Input aria-label="资源 ID" placeholder="资源 UUID" />
      </Form.Item>
      <Form.Item name="created_from" label="开始时间">
        <Input aria-label="开始时间" type="datetime-local" />
      </Form.Item>
      <Form.Item
        name="created_to"
        label="结束时间"
        rules={[
          {
            validator: (_, value: string | undefined) =>
              validateEndTime(form.getFieldValue('created_from'), value),
          },
        ]}
      >
        <Input aria-label="结束时间" type="datetime-local" />
      </Form.Item>
      <Button htmlType="submit" type="primary">
        查询审计
      </Button>
      <Button
        onClick={() => {
          form.resetFields()
          onSearch({})
        }}
      >
        重置筛选
      </Button>
    </Form>
  )
}

function normalizeFilters(values: AuditFormValues): AuditFormValues {
  return {
    action: values.action?.trim() || undefined,
    actor_user_id: values.actor_user_id?.trim() || undefined,
    resource_type: values.resource_type?.trim() || undefined,
    resource_id: values.resource_id?.trim() || undefined,
    created_from: toUtc(values.created_from),
    created_to: toUtc(values.created_to),
  }
}

function toUtc(value?: string): string | undefined {
  return value ? new Date(value).toISOString() : undefined
}

function validateEndTime(start?: string, end?: string): Promise<void> {
  if (start && end && new Date(end) < new Date(start))
    return Promise.reject(new Error('结束时间不能早于开始时间'))
  return Promise.resolve()
}

function AuditDetails({
  entry,
  onClose,
}: {
  entry: OrganizationAuditLog | null
  onClose: () => void
}) {
  const trace = entry?.details.trace_id
  return (
    <Modal
      open={entry !== null}
      title="审计只读详情"
      onCancel={onClose}
      footer={<Button onClick={onClose}>关闭详情</Button>}
    >
      {entry && (
        <>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="操作者">
              {entry.actor_user_id ?? '系统 / 已删除用户'}
            </Descriptions.Item>
            <Descriptions.Item label="资源">
              {entry.resource_type} / {entry.resource_id ?? '未记录'}
            </Descriptions.Item>
            <Descriptions.Item label="组织">{entry.organization_id}</Descriptions.Item>
            <Descriptions.Item label="项目">{entry.project_id ?? '组织范围'}</Descriptions.Item>
            <Descriptions.Item label="Trace">
              {typeof trace === 'string' ? trace : '未记录'}
            </Descriptions.Item>
          </Descriptions>
          <Typography.Paragraph type="secondary">
            以下仅展示服务端已授权返回的审计详情。
          </Typography.Paragraph>
          <Descriptions
            column={1}
            size="small"
            items={Object.entries(entry.details).map(([key, value]) => ({
              key,
              label: key,
              children: typeof value === 'string' ? value : JSON.stringify(value),
            }))}
          />
        </>
      )}
    </Modal>
  )
}
