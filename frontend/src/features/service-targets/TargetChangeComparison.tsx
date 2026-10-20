import { Card, Col, Empty, Row, Typography } from 'antd'
import type { RequestService, ServiceEndpoint } from '../../lib/api'
import type { UpdateEndpointInput, UpdateRequestServiceInput } from './service-target-service'

type Props =
  | { kind: 'service'; before: RequestService; after: UpdateRequestServiceInput }
  | { kind: 'endpoint'; before: ServiceEndpoint; after: UpdateEndpointInput }

const serviceFields: readonly [keyof UpdateRequestServiceInput, string][] = [
  ['name', '名称'],
  ['description', '描述'],
  ['owner_team', '负责团队'],
  ['service_type', '服务协议'],
  ['enabled', '启用服务'],
]
const endpointFields: readonly [keyof UpdateEndpointInput, string][] = [
  ['variant', '地址变体'],
  ['base_url', '部署地址'],
  ['enabled', '启用地址'],
  ['connect_timeout_ms', '连接超时（毫秒）'],
  ['read_timeout_ms', '读取超时（毫秒）'],
  ['tls_verify', 'TLS 证书校验'],
  ['proxy_ref', '代理引用'],
  ['headers', '请求头'],
  ['variables', '变量'],
  ['secret_refs', '凭据引用'],
  ['health_check_path', '健康检查路径'],
  ['health_expected_status', '健康检查预期状态码'],
]

export default function TargetChangeComparison(props: Props) {
  const rows =
    props.kind === 'service'
      ? changedValues(props.before, props.after, serviceFields)
      : changedValues(props.before, props.after, endpointFields)
  return (
    <Card size="small" title="变更对比（打开编辑时的配置 → 待保存候选）">
      {rows.length ? (
        rows.map((row) => (
          <section key={row.label} className="request-target-impact-item">
            <Typography.Text strong>{row.label}</Typography.Text>
            <Row gutter={12}>
              <Col xs={24} md={12}>
                <Typography.Text type="secondary">修改前</Typography.Text>
                <pre className="request-target-change-value">{row.before}</pre>
              </Col>
              <Col xs={24} md={12}>
                <Typography.Text type="secondary">待保存</Typography.Text>
                <pre className="request-target-change-value">{row.after}</pre>
              </Col>
            </Row>
          </section>
        ))
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有字段变更" />
      )}
    </Card>
  )
}

function changedValues<T extends object>(
  before: T,
  after: Partial<T>,
  fields: readonly [keyof T, string][],
) {
  return fields.flatMap(([key, label]) => {
    if (after[key] === undefined) return []
    const current = formatValue(before[key])
    const candidate = formatValue(after[key])
    return current === candidate ? [] : [{ label, before: current, after: candidate }]
  })
}
function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未配置'
  if (typeof value === 'boolean') return value ? '启用' : '停用'
  if (Array.isArray(value)) return value.join(', ') || '未配置'
  if (typeof value === 'object')
    return (
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([name, item]) => `${name}: ${item}`)
        .join('\n') || '未配置'
    )
  return String(value)
}
