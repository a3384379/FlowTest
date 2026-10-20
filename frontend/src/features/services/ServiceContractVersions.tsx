import { Descriptions, Space, Table, Tag, Typography } from 'antd'
import CatalogPagination from '../../components/CatalogPagination'
import { useCatalogQuery } from '../../lib/catalog-query'
import {
  listServiceContractVersions,
  type ServiceContractVersion,
} from '../contracts/contract-hub-service'

const roleLabels = Object.freeze({ consumer: '消费方', provider: '提供方', both: '消费方及提供方' })

export default function ServiceContractVersions({
  projectId,
  serviceId,
}: {
  projectId: string
  serviceId: string
}) {
  const query = useCatalogQuery(
    'service-contract-versions',
    projectId,
    (page) => listServiceContractVersions(projectId, serviceId, page),
    true,
    serviceId,
  )
  return (
    <section aria-label="服务契约版本">
      <Typography.Title level={5}>契约版本记录</Typography.Title>
      <Typography.Paragraph type="secondary">
        Pact 使用消费者版本，OpenAPI 使用导入时记录的提供方版本；部署结论见对应验证记录。
      </Typography.Paragraph>
      {!query.isError && (
        <Table<ServiceContractVersion>
          size="small"
          rowKey={(item) => `${item.kind}:${item.id}`}
          loading={query.isLoading}
          dataSource={query.data?.items ?? []}
          pagination={false}
          locale={{ emptyText: '当前服务未登记契约版本记录' }}
          expandable={{
            expandedRowRender: (item) => (
              <Descriptions
                column={1}
                size="small"
                items={[
                  {
                    key: 'id',
                    label: '记录 ID',
                    children: (
                      <Typography.Text code copyable>
                        {item.id}
                      </Typography.Text>
                    ),
                  },
                  { key: 'source', label: '固定来源名称', children: item.source_name },
                  {
                    key: 'time',
                    label: '登记时间（北京时间）',
                    children: formatTime(item.created_at),
                  },
                ]}
              />
            ),
          }}
          columns={[
            {
              title: '契约版本 / 来源',
              render: (_: unknown, item) => (
                <Space orientation="vertical" size={2}>
                  <Space wrap>
                    <Tag>{item.kind === 'openapi' ? 'OpenAPI' : 'Pact'}</Tag>
                    <Typography.Text>{versionLabel(item)}</Typography.Text>
                  </Space>
                  <Typography.Text type="secondary">{item.source_name}</Typography.Text>
                  <Tag color={item.status === 'failed' ? 'red' : undefined}>
                    {statusLabel(item)}
                  </Tag>
                </Space>
              ),
            },
            {
              title: '本服务角色',
              dataIndex: 'service_role',
              render: (role: ServiceContractVersion['service_role']) => roleLabels[role],
            },
          ]}
        />
      )}
      <CatalogPagination query={query} label="契约版本" />
    </section>
  )
}

function versionLabel(item: ServiceContractVersion): string {
  if (item.version === null) return item.kind === 'pact' ? '未记录消费者版本' : '未记录提供方版本'
  return `${item.kind === 'pact' ? '消费者版本' : '提供方版本'} ${item.version}`
}
function statusLabel(item: ServiceContractVersion): string {
  if (item.status === 'failed') return '导入失败'
  return item.kind === 'pact' ? '文档已登记' : '导入完成'
}
function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
