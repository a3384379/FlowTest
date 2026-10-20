import { DeleteOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tabs,
} from 'antd'

import CatalogPagination from '../../components/CatalogPagination'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { apiErrorMessage, type MockService } from '../../lib/api'
import { useCatalogQuery } from '../../lib/catalog-query'
import {
  createMockRoute,
  deleteMockRoute,
  listMockLogs,
  listMockRoutes,
  type MockRouteInput,
} from './data-source-service'

export default function MockRouteWorkspace({
  projectId,
  service,
  canEdit,
}: {
  projectId: string
  service: MockService
  canEdit: boolean
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const routes = useQuery({
    queryKey: ['mock-routes', projectId, service.id],
    queryFn: () => listMockRoutes(projectId, service.id),
  })
  const logs = useCatalogQuery(
    'mock-logs',
    projectId,
    (page) => listMockLogs(projectId, service.id, page, 20),
    true,
    service.id,
    { refetchInterval: 2_000 },
  )
  const createRouteMutation = useMutation({
    mutationFn: (input: MockRouteInput) => createMockRoute(projectId, service.id, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['mock-routes', projectId, service.id] })
      void message.success('Mock 路由已创建')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const removeRouteMutation = useMutation({
    mutationFn: (routeId: string) => deleteMockRoute(projectId, service.id, routeId),
    onSuccess: async () =>
      queryClient.invalidateQueries({ queryKey: ['mock-routes', projectId, service.id] }),
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  return (
    <Row gutter={16}>
      {canEdit && (
        <Col xs={24} xl={9}>
          <MockRouteForm
            pending={createRouteMutation.isPending}
            onFinish={createRouteMutation.mutate}
          />
        </Col>
      )}
      <Col xs={24} xl={canEdit ? 15 : 24}>
        <QueryFailureNotice queries={[routes, logs]} />
        <CatalogPagination query={logs} label="Mock 请求日志" />
        <Tabs
          items={[
            {
              key: 'routes',
              label: '路由规则',
              children: (
                <Table
                  rowKey="id"
                  size="small"
                  loading={routes.isLoading}
                  dataSource={routes.data ?? []}
                  pagination={false}
                  columns={[
                    { title: '名称', dataIndex: 'name' },
                    { title: '方法', dataIndex: 'method' },
                    { title: '路径', dataIndex: 'path_pattern' },
                    { title: '场景', dataIndex: 'scenario', render: (value) => value || '默认' },
                    { title: '状态码', dataIndex: 'response_status' },
                    {
                      title: '操作',
                      render: (_, item) =>
                        canEdit ? (
                          <Popconfirm
                            title="确认删除路由？"
                            onConfirm={() => removeRouteMutation.mutate(item.id)}
                          >
                            <Button
                              type="text"
                              danger
                              icon={<DeleteOutlined />}
                              aria-label="删除 Mock 路由"
                            />
                          </Popconfirm>
                        ) : null,
                    },
                  ]}
                />
              ),
            },
            {
              key: 'logs',
              label: '请求日志',
              children: (
                <Table
                  rowKey="id"
                  size="small"
                  loading={logs.isLoading}
                  dataSource={logs.data?.items ?? []}
                  columns={[
                    { title: '时间', dataIndex: 'created_at' },
                    { title: '方法', dataIndex: 'method' },
                    { title: '路径', dataIndex: 'path' },
                    {
                      title: '匹配',
                      dataIndex: 'matched',
                      render: (value) => (value ? '是' : '否'),
                    },
                    { title: '状态码', dataIndex: 'response_status' },
                    { title: '耗时', dataIndex: 'duration_ms', render: (value) => `${value} ms` },
                  ]}
                />
              ),
            },
          ]}
        />
      </Col>
    </Row>
  )
}

function MockRouteForm({
  pending,
  onFinish,
}: {
  pending: boolean
  onFinish: (input: MockRouteInput) => void
}) {
  const [form] = Form.useForm<Record<string, unknown>>()
  return (
    <Card title="新增路由规则" size="small">
      <Form
        name="mock-route"
        form={form}
        layout="vertical"
        initialValues={{
          method: 'GET',
          response_status: 200,
          delay_ms: 0,
          priority: 0,
          is_enabled: true,
          query_conditions: '{}',
          header_conditions: '{}',
          response_headers: '{}',
          response_body: '{}',
        }}
        onFinish={(values) => onFinish(mockRouteInput(values))}
      >
        <Form.Item name="name" label="名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Space align="start">
          <Form.Item name="method" label="方法">
            <Select className="method-select" options={httpMethodOptions} />
          </Form.Item>
          <Form.Item name="path_pattern" label="路径" rules={[{ required: true }]}>
            <Input placeholder="/users/{user_id}" />
          </Form.Item>
        </Space>
        <Form.Item name="scenario" label="场景（可选）">
          <Input placeholder="happy" />
        </Form.Item>
        <Form.Item name="query_conditions" label="Query 条件（JSON）" rules={[jsonRule]}>
          <Input.TextArea rows={2} className="code-input" />
        </Form.Item>
        <Form.Item name="header_conditions" label="Header 条件（JSON）" rules={[jsonRule]}>
          <Input.TextArea rows={2} className="code-input" />
        </Form.Item>
        <Form.Item name="response_body" label="响应模板（JSON）" rules={[jsonRule]}>
          <Input.TextArea rows={5} className="code-input" />
        </Form.Item>
        <Form.Item name="response_headers" label="响应 Header（JSON）" rules={[jsonRule]}>
          <Input.TextArea rows={2} className="code-input" />
        </Form.Item>
        <Space align="start">
          <Form.Item name="response_status" label="状态码">
            <InputNumber min={100} max={599} />
          </Form.Item>
          <Form.Item name="delay_ms" label="延迟 ms">
            <InputNumber min={0} max={30000} />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <InputNumber min={-1000} max={1000} />
          </Form.Item>
        </Space>
        <Button type="primary" htmlType="submit" loading={pending}>
          保存路由
        </Button>
      </Form>
    </Card>
  )
}

function mockRouteInput(values: Record<string, unknown>): MockRouteInput {
  return {
    name: String(values.name),
    method: values.method as MockRouteInput['method'],
    path_pattern: String(values.path_pattern),
    query_conditions: jsonRecord(values.query_conditions),
    header_conditions: jsonRecord(values.header_conditions),
    response_status: Number(values.response_status),
    response_headers: jsonRecord(values.response_headers),
    response_body: JSON.parse(String(values.response_body)),
    delay_ms: Number(values.delay_ms),
    scenario: values.scenario ? String(values.scenario) : null,
    priority: Number(values.priority),
    is_enabled: true,
  }
}

function jsonRecord(value: unknown): Record<string, string> {
  return JSON.parse(String(value)) as Record<string, string>
}

const jsonRule = {
  validator: async (_: unknown, value: string) => {
    try {
      JSON.parse(value)
      return Promise.resolve()
    } catch {
      return Promise.reject(new Error('请输入有效 JSON'))
    }
  },
}

const httpMethodOptions = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((value) => ({
  value,
  label: value,
}))
