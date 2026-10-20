import { Card, Form, Input, InputNumber, Select, Space, Switch, Button, Typography } from 'antd'

import './mock-route-workspace.css'

import type { MockRoute } from '../../lib/api'
import type { MockRouteInput } from './data-source-service'
import {
  mapRule,
  jsonValueRule,
  mockHttpMethods,
  mockRouteFields,
  mockRouteInput,
  type MockRouteFields,
} from './mock-form-values'
import MockPreviewPanel from './MockPreviewPanel'
import { useMockPreviewState } from './use-mock-preview'
import MockStringMapEditor from './MockStringMapEditor'

export default function MockRouteForm({
  projectId,
  serviceId,
  route,
  canEdit,
  readable,
  pending,
  previewScope = '',
  onDirty,
  onFinish,
}: {
  projectId: string
  serviceId: string
  route: MockRoute | null
  canEdit: boolean
  readable: boolean
  pending: boolean
  previewScope?: string
  onDirty: () => void
  onFinish: (input: MockRouteInput) => void
}) {
  const [form] = Form.useForm<MockRouteFields>()
  const preview = useMockPreviewState(`${readable && !pending}:${previewScope}`)
  const disabled = !canEdit || !readable || pending
  return (
    <Card title={routeTitle(route, canEdit)} size="small">
      <div className="mock-route-edit-layout">
        <Form
          name="mock-route"
          form={form}
          layout="vertical"
          disabled={disabled}
          initialValues={mockRouteFields(route)}
          onValuesChange={() => {
            preview.invalidate()
            onDirty()
          }}
          onFinish={(values) => {
            if (!disabled) onFinish(mockRouteInput(values))
          }}
        >
          <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true }]}>
            <Input maxLength={160} />
          </Form.Item>
          <Space wrap align="start">
            <Form.Item name="method" label="方法">
              <Select className="method-select" options={mockHttpMethods} />
            </Form.Item>
            <Form.Item
              name="path_pattern"
              label="路径"
              rules={[{ required: true, pattern: /^\//, message: '路径必须以 / 开头' }]}
            >
              <Input maxLength={1024} placeholder="/users/{user_id}" />
            </Form.Item>
          </Space>
          <Form.Item name="scenario" label="场景（可选）">
            <Input maxLength={80} placeholder="happy" />
          </Form.Item>
          <Form.Item name="query_conditions" label="Query 条件" rules={[mapRule(false)]}>
            <MockStringMapEditor label="Query 条件" disabled={disabled} />
          </Form.Item>
          <Form.Item name="header_conditions" label="Header 条件" rules={[mapRule(true)]}>
            <MockStringMapEditor label="Header 条件" header disabled={disabled} />
          </Form.Item>
          <MockResponseBodyFields disabled={disabled} />
          <Form.Item name="response_headers" label="响应 Header" rules={[mapRule(true)]}>
            <MockStringMapEditor label="响应 Header" header disabled={disabled} />
          </Form.Item>
          <Space wrap align="start">
            <Form.Item name="response_status" label="状态码" rules={[{ required: true }]}>
              <InputNumber min={100} max={599} />
            </Form.Item>
            <Form.Item name="delay_ms" label="延迟 ms" rules={[{ required: true }]}>
              <InputNumber min={0} max={30000} />
            </Form.Item>
            <Form.Item name="priority" label="优先级" rules={[{ required: true }]}>
              <InputNumber min={-1000} max={1000} />
            </Form.Item>
          </Space>
          <Form.Item name="is_enabled" label="启用此规则" valuePropName="checked">
            <Switch />
          </Form.Item>
          {canEdit && (
            <Button type="primary" htmlType="submit" loading={pending} disabled={!readable}>
              保存路由
            </Button>
          )}
        </Form>

        <MockPreviewPanel
          projectId={projectId}
          serviceId={serviceId}
          routeId={route?.id ?? null}
          draftForm={form}
          readable={readable && !pending}
          state={preview}
        />
      </div>
    </Card>
  )
}

function routeTitle(route: MockRoute | null, canEdit: boolean): string {
  if (!route) return '新增路由规则'
  return canEdit ? '编辑路由规则' : '规则详情'
}

function MockResponseBodyFields({ disabled }: { disabled: boolean }) {
  const form = Form.useFormInstance<MockRouteFields>()
  const mode = Form.useWatch('body_mode', form) ?? 'json'
  return (
    <>
      <Form.Item name="body_mode" label="响应体类型">
        <Select
          disabled={disabled}
          aria-label="响应体类型"
          options={[
            { value: 'json', label: 'JSON 值' },
            { value: 'text', label: '文本（JSON 字符串值）' },
          ]}
        />
      </Form.Item>
      <Typography.Paragraph type="secondary">
        响应以 JSON 返回；文本模式保存字符串值。模板支持
        path、query、header、body，完整变量保留原值类型，字符串插值只支持标量。响应头按字面返回。
      </Typography.Paragraph>
      <Form.Item
        name="response_body"
        label={mode === 'json' ? '响应模板（JSON）' : '响应模板（文本）'}
        dependencies={['body_mode']}
        rules={[
          {
            validator: async (_, value: string) => {
              if (form.getFieldValue('body_mode') === 'json')
                await jsonValueRule.validator(_, value)
            },
          },
        ]}
      >
        <Input.TextArea rows={5} className="code-input" />
      </Form.Item>
    </>
  )
}
