import { Alert, Button, Collapse, Form, Input, Select, Space, Tag, Typography } from 'antd'
import type { FormInstance } from 'antd'

import { previewMockRoute, type MockPreviewResult } from './data-source-service'
import {
  mapRule,
  jsonValueRule,
  mockHttpMethods,
  mockRouteInput,
  readStringMap,
  stringMapDraft,
  type MockRouteFields,
  type StringMapDraft,
} from './mock-form-values'
import { useMockPreviewState, applyPreviewError } from './use-mock-preview'
import MockStringMapEditor from './MockStringMapEditor'

type RequestFields = {
  method: MockRouteFields['method']
  path: string
  query: StringMapDraft
  headers: StringMapDraft
  body: string
}

export default function MockPreviewPanel({
  projectId,
  serviceId,
  routeId,
  draftForm,
  readable,
  state,
}: {
  projectId: string
  serviceId: string
  routeId: string | null
  draftForm: FormInstance<MockRouteFields>
  readable: boolean
  state: ReturnType<typeof useMockPreviewState>
}) {
  const [form] = Form.useForm<RequestFields>()
  async function run() {
    const current = state.start()
    try {
      const [draft, request] = await Promise.all([
        draftForm.validateFields(),
        form.validateFields(),
      ])
      if (!current()) return
      const result = await previewMockRoute(projectId, serviceId, {
        draft: mockRouteInput(draft),
        route_id: routeId,
        request: {
          method: request.method,
          path: request.path,
          query: readStringMap(request.query),
          headers: readStringMap(request.headers, true),
          body: JSON.parse(request.body),
        },
      })
      if (current()) state.setResult(result)
    } catch (error) {
      if (current()) applyPreviewError(error, routeId, draftForm, state.setError)
    } finally {
      if (current()) state.setPending(false)
    }
  }
  return (
    <Collapse
      items={[
        {
          key: 'preview',
          label: '合成请求与只读预览',
          children: (
            <Space orientation="vertical" className="full-width">
              <Typography.Paragraph type="secondary">
                输入应用收到的路径和合成数据。预览比较本服务规则，不保存，不发送外部请求，不执行延迟。
                场景优先读取 Query 的 _scenario，其次读取
                X-FlowTest-Scenario；优先级高者先匹配，同优先级先创建者优先。
              </Typography.Paragraph>
              <Form
                form={form}
                layout="vertical"
                onValuesChange={state.invalidate}
                initialValues={{
                  method: 'GET',
                  path: '/',
                  query: stringMapDraft(),
                  headers: stringMapDraft(),
                  body: '{}',
                }}
              >
                <Form.Item name="method" label="合成请求方法">
                  <Select options={mockHttpMethods} />
                </Form.Item>
                <Form.Item
                  name="path"
                  label="合成请求路径"
                  rules={[{ required: true, pattern: /^\//, message: '路径必须以 / 开头' }]}
                >
                  <Input maxLength={1024} placeholder="/orders/42" />
                </Form.Item>
                <Form.Item name="query" label="合成 Query" rules={[mapRule(false)]}>
                  <MockStringMapEditor label="合成 Query" />
                </Form.Item>
                <Form.Item name="headers" label="合成 Header" rules={[mapRule(true)]}>
                  <MockStringMapEditor label="合成 Header" header />
                </Form.Item>
                <Form.Item name="body" label="合成请求体（JSON）" rules={[jsonValueRule]}>
                  <Input.TextArea rows={3} />
                </Form.Item>
              </Form>
              <Button disabled={!readable} loading={state.pending} onClick={() => void run()}>
                预览匹配与响应
              </Button>
              {readable && state.error && <Alert type="error" showIcon title={state.error} />}
              {readable && state.result && <MockPreviewEvidence result={state.result} />}
            </Space>
          ),
        },
      ]}
    />
  )
}

function MockPreviewEvidence({ result }: { result: MockPreviewResult }) {
  const selected = result.selected
  return (
    <Space orientation="vertical" className="full-width" role="region" aria-label="Mock 预览结果">
      {!result.service_enabled && (
        <Alert type="warning" title="服务已停用，实际请求不会匹配该服务" />
      )}
      <Typography.Text>
        当前草稿：{result.draft_matches ? '符合全部匹配条件' : '未命中全部条件'}
      </Typography.Text>
      {result.checks.map((check) => (
        <div key={check.field}>
          <Tag color={check.matched ? 'green' : 'default'}>{check.matched ? '通过' : '未通过'}</Tag>
          {check.message}
        </div>
      ))}
      <Typography.Text>
        {selected
          ? `实际命中：${selected.name}（${selected.is_draft ? '当前草稿' : '已保存规则'}），优先级 ${selected.priority}，场景 ${selected.scenario ?? '默认'}，延迟 ${selected.delay_ms} ms（仅展示）`
          : '没有实际命中的规则'}
      </Typography.Text>
      {result.warnings.map((warning, index) => (
        <Alert
          key={index}
          type="warning"
          title={`${warning.field}${warning.pointer || '（根值）'}：${warning.message}`}
          description={warning.route_id ? `规则 ID：${warning.route_id}` : '新建草稿'}
        />
      ))}
      {result.response && (
        <>
          <Typography.Text>响应状态码：{result.response.status_code}</Typography.Text>
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              overflowWrap: 'anywhere',
              maxHeight: 360,
              overflow: 'auto',
            }}
          >
            {JSON.stringify(result.response, null, 2)}
          </pre>
        </>
      )}
    </Space>
  )
}
