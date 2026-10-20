import {
  Alert,
  Button,
  Card,
  Collapse,
  Descriptions,
  Empty,
  Form,
  Input,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'
import type { FormInstance } from 'antd'
import type { Environment, RequestService, SecretMetadata, ServiceEndpoint } from '../../lib/api'
import type { CreateEndpointInput, EndpointConnectivity } from './service-target-service'

type Props = {
  readOnly: boolean
  environments: Environment[]
  selected?: Environment
  environmentId: string | null
  onEnvironmentChange: (value: string) => void
  environmentSelectionInvalid: boolean
  environmentPlaceholder: string
  environmentStatus: 'error' | undefined
  serviceOptions: Array<{ value: string; label: string }>
  endpointForm: FormInstance<CreateEndpointInput>
  endpoints: ServiceEndpoint[]
  service?: RequestService
  secrets: SecretMetadata[]
  connectivity: Record<string, EndpointConnectivity>
  loading: boolean
  endpointsLoading: boolean
  endpointSubmitting: boolean
  defaultSubmitting: boolean
  onDefaultChange: (value: string | null) => void
  onEndpointFinish: (values: CreateEndpointInput) => void
  onEditEndpoint: (endpoint: ServiceEndpoint) => void
  onCheckConnectivity: (endpointId: string) => void
  actionLoading: boolean
}

export default function EnvironmentEndpointCard(props: Props) {
  const endpoints = props.endpoints.filter((item) => item.service_id === props.service?.id)
  return (
    <Card title="部署地址与变体" loading={props.loading} className="request-target-environment">
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <label>
          当前管理环境
          <Select
            aria-label="目标环境"
            style={{ width: '100%', minWidth: 0 }}
            value={props.environmentId ?? undefined}
            onChange={props.onEnvironmentChange}
            placeholder={props.environmentPlaceholder}
            status={props.environmentStatus}
            options={props.environments.map((item) => ({ value: item.id, label: item.name }))}
          />
        </label>
        <EnvironmentBinding {...props} />
        <Typography.Title level={5}>
          {props.service?.name ?? '请选择逻辑服务'} · 部署地址
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          一个服务可在同一环境配置多个地址变体。default
          是默认变体，编排节点可显式选择其他变体。接口绑定在下方按项目目录管理。
        </Typography.Paragraph>
        {props.endpointsLoading ? (
          <Typography.Text>正在读取部署地址</Typography.Text>
        ) : endpoints.length ? (
          endpoints.map((item) => <EndpointDetail key={item.id} endpoint={item} {...props} />)
        ) : (
          <Empty
            description={
              props.service ? '所选服务在当前环境没有地址变体' : '选择逻辑服务后查看部署地址'
            }
          />
        )}
        <Collapse
          items={[
            { key: 'create', label: '新增地址变体', children: <EndpointCreate {...props} /> },
          ]}
        />
      </Space>
    </Card>
  )
}

function EnvironmentBinding(props: Props) {
  if (!props.selected)
    return (
      <Alert
        showIcon
        type={props.environmentSelectionInvalid ? 'warning' : 'info'}
        title={props.environmentSelectionInvalid ? props.environmentPlaceholder : '请先选择环境'}
      />
    )
  return (
    <div>
      <Typography.Text>环境默认服务</Typography.Text>
      <Select
        aria-label="环境默认服务"
        allowClear
        style={{ width: '100%', minWidth: 0 }}
        value={props.selected.default_service_id ?? null}
        options={props.serviceOptions}
        onChange={(value?: string) => props.onDefaultChange(value ?? null)}
        loading={props.defaultSubmitting}
        disabled={props.readOnly}
      />
      <Typography.Text type="secondary">
        接口和节点均未绑定服务时使用；清空后使用环境基础地址。
      </Typography.Text>
    </div>
  )
}

function EndpointCreate(props: Props) {
  return (
    <Form<CreateEndpointInput>
      key={props.environmentId}
      form={props.endpointForm}
      name="request-endpoint-create"
      layout="vertical"
      onFinish={props.onEndpointFinish}
      disabled={!props.environmentId || props.readOnly || props.endpointSubmitting}
    >
      <Form.Item
        name="service_id"
        label="逻辑服务"
        rules={[{ required: true, message: '请选择逻辑服务' }]}
      >
        <Select
          aria-label="新增地址的逻辑服务"
          placeholder="选择逻辑服务"
          options={props.serviceOptions}
        />
      </Form.Item>
      <Form.Item name="variant" label="地址变体" initialValue="default">
        <Input aria-label="新增地址变体" placeholder="default" />
      </Form.Item>
      <Form.Item
        name="base_url"
        label="部署地址"
        rules={[{ required: true, message: '请输入部署地址' }]}
      >
        <Input aria-label="新增部署地址" placeholder="https://orders.example.com" />
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={props.endpointSubmitting}>
        添加部署地址
      </Button>
    </Form>
  )
}

function EndpointDetail({ endpoint, ...props }: Props & { endpoint: ServiceEndpoint }) {
  return (
    <Card
      size="small"
      className="request-target-endpoint"
      title={
        <Space wrap>
          <Typography.Text strong>{endpoint.variant}</Typography.Text>
          <Tag color={endpoint.enabled ? 'success' : 'default'}>
            {endpoint.enabled ? '启用' : '停用'}
          </Tag>
          <Typography.Text type="secondary">修订 r{endpoint.revision}</Typography.Text>
        </Space>
      }
    >
      <Typography.Paragraph copyable className="request-target-url">
        {endpoint.base_url}
      </Typography.Paragraph>
      <Space wrap style={{ marginBottom: 12 }}>
        <Button
          size="small"
          onClick={() => props.onEditEndpoint(endpoint)}
          loading={props.actionLoading}
        >
          影响预览 / 编辑
        </Button>
        <Button
          size="small"
          onClick={() => props.onCheckConnectivity(endpoint.id)}
          loading={props.actionLoading}
        >
          检查连通性
        </Button>
        <ConnectivityResult result={props.connectivity[endpoint.id]} />
      </Space>
      <Collapse
        size="small"
        items={[
          {
            key: 'details',
            label: '连接、凭据与健康检查详情',
            children: (
              <Descriptions
                column={1}
                size="small"
                items={[
                  {
                    key: 'timeout',
                    label: '连接 / 读取超时',
                    children: `${endpoint.connect_timeout_ms} / ${endpoint.read_timeout_ms} 毫秒`,
                  },
                  {
                    key: 'tls',
                    label: 'TLS 证书',
                    children: endpoint.tls_verify ? '校验' : '不校验',
                  },
                  { key: 'proxy', label: '代理引用', children: endpoint.proxy_ref || '未配置' },
                  {
                    key: 'maps',
                    label: '请求头 / 变量',
                    children: `${Object.keys(endpoint.headers).length} / ${Object.keys(endpoint.variables ?? {}).length} 项（编辑中查看）`,
                  },
                  {
                    key: 'refs',
                    label: '凭据引用',
                    children: endpoint.secret_refs.length
                      ? endpoint.secret_refs.map((name) => (
                          <Tag key={name}>
                            {name}
                            {props.secrets.some((item) => item.name === name) ? '' : '（不可用）'}
                          </Tag>
                        ))
                      : '未配置',
                  },
                  {
                    key: 'health',
                    label: '健康检查',
                    children: `${endpoint.health_check_path || '未配置路径'} / 预期 ${endpoint.health_expected_status ?? '任意状态码'}`,
                  },
                ]}
              />
            ),
          },
        ]}
      />
    </Card>
  )
}

function ConnectivityResult({ result }: { result?: EndpointConnectivity }) {
  if (!result) return <Tag>未检查</Tag>
  const labels: Record<string, string> = {
    reachable: '可连通',
    unreachable: '不可连通',
    timeout: '连接超时',
    unexpected_status: '状态码不符',
  }
  return (
    <Tag color={result.status === 'reachable' ? 'success' : 'warning'}>
      {labels[result.status] ?? result.status} {result.http_status ?? result.error_code ?? ''}
    </Tag>
  )
}
