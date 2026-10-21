import {
  Alert,
  App,
  Button,
  Col,
  Form,
  Input,
  Modal,
  Row,
  Space,
  Table,
  Tabs,
  Typography,
} from 'antd'
import type { NamePath } from 'antd/es/form/interface'
import { useContext, useEffect, useState } from 'react'
import { UNSAFE_DataRouterContext, useBlocker } from 'react-router-dom'
import type { EnvironmentTemplateInput, EnvironmentTemplateVersion } from './environment-service'
import EnvironmentManifestFields from './EnvironmentManifestFields'
import {
  defaultEnvironmentManifest,
  ManifestFieldError,
  parseEnvironmentManifest,
  validateEnvironmentManifest,
} from './environment-template-manifest'
import './environment-lab.css'

export default function EnvironmentTemplateDialog({
  base,
  submitting,
  onClose,
  onSubmit,
}: {
  base?: EnvironmentTemplateVersion
  submitting: boolean
  onClose: () => void
  onSubmit: (input: EnvironmentTemplateInput) => Promise<boolean>
}) {
  const [form] = Form.useForm<EnvironmentTemplateInput>()
  const [initial] = useState<EnvironmentTemplateInput>(() => ({
    template_key: base?.template_key ?? 'platform.web',
    display_name: base?.display_name ?? '受控 Web 环境',
    description: base?.description ?? '',
    manifest: structuredClone(base?.manifest ?? defaultEnvironmentManifest()),
  }))
  const [dirty, setDirty] = useState(false)
  const [json, setJson] = useState('')
  const [jsonPending, setJsonPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const manifest = Form.useWatch((value: EnvironmentTemplateInput) => value.manifest, {
    form,
    preserve: true,
  })
  const changes = base ? manifestDifferences(base.manifest, manifest ?? initial.manifest) : []
  const [tab, setTab] = useState('form')
  const { modal } = App.useApp()
  function updateChanges() {
    const value = form.getFieldsValue(true) as EnvironmentTemplateInput
    setDirty(JSON.stringify(value) !== JSON.stringify(initial))
    setError(null)
  }
  function close() {
    if (submitting) return
    if (!dirty && !jsonPending) {
      onClose()
      return
    }
    modal.confirm({
      title: '模板修改尚未保存',
      content: '关闭将放弃当前表单和未应用的JSON修改。',
      okText: '放弃修改',
      cancelText: '继续编辑',
      onOk: onClose,
    })
  }
  function exportJson() {
    if (jsonPending) return
    setJson(JSON.stringify(form.getFieldValue('manifest'), null, 2))
    setTab('json')
  }
  function applyJson() {
    try {
      const manifest = parseEnvironmentManifest(json)
      form.setFieldValue('manifest', manifest)
      setJsonPending(false)
      updateChanges()
      setTab('form')
    } catch (caught) {
      setError(errorText(caught))
    }
  }
  async function submit() {
    if (jsonPending) {
      setError('高级JSON尚未应用，请先应用或放弃JSON修改')
      return
    }
    try {
      const value = form.getFieldsValue(true) as EnvironmentTemplateInput
      const manifest = validateEnvironmentManifest(value.manifest)
      if (await onSubmit({ ...value, manifest })) {
        setDirty(false)
        onClose()
      }
    } catch (caught) {
      if (caught instanceof ManifestFieldError)
        form.setFields([
          {
            name: ['manifest', ...caught.path] as NamePath<EnvironmentTemplateInput>,
            errors: [caught.message],
          },
        ])
      setError(errorText(caught))
      setTab('form')
    }
  }
  return (
    <>
      <TemplateDraftProtection dirty={dirty || jsonPending} />
      <Modal
        open
        title={base ? `为 ${base.display_name} 创建签名版本` : '注册管理员签名环境模板'}
        width={1040}
        onCancel={close}
        onOk={() => form.submit()}
        confirmLoading={submitting}
        cancelButtonProps={{ disabled: submitting }}
        closable={!submitting}
        mask={{ closable: !submitting }}
        keyboard={!submitting}
        destroyOnHidden
        className="environment-template-dialog"
      >
        {base && (
          <Alert
            type="info"
            title={`基于固定 v${base.version} · ${base.id}`}
            description="完整保留原版本服务、依赖、资源与Seed；新版本由服务端重新校验并签名。"
          />
        )}
        {error && <Alert showIcon type="error" title="模板尚未提交" description={error} />}
        <Form
          form={form}
          name="environment-template-editor"
          layout="vertical"
          initialValues={initial}
          disabled={submitting}
          onValuesChange={updateChanges}
          onFinish={() => void submit()}
        >
          <Row gutter={16}>
            <Col xs={24} sm={8}>
              <Form.Item
                name="template_key"
                label="模板标识"
                rules={[
                  { required: true },
                  {
                    pattern: /^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$/,
                    message: '请输入3至120位小写模板标识',
                  },
                ]}
              >
                <Input disabled={Boolean(base)} maxLength={120} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={8}>
              <Form.Item name="display_name" label="显示名称" rules={[{ required: true }]}>
                <Input disabled={Boolean(base)} maxLength={160} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={8}>
              <Form.Item name="description" label="说明">
                <Input disabled={Boolean(base)} maxLength={1000} />
              </Form.Item>
            </Col>
          </Row>
          <Tabs
            activeKey={tab}
            onChange={(key) => {
              if (key === 'json') exportJson()
              else setTab(key)
            }}
            items={[
              {
                key: 'form',
                label: '可视化配置',
                forceRender: true,
                children: <EnvironmentManifestFields />,
              },
              {
                key: 'json',
                label: '高级 JSON',
                forceRender: true,
                children: (
                  <Space orientation="vertical" className="environment-field-stack">
                    <Typography.Text>
                      JSON通过相同合同校验后显式应用到表单；尚未应用时不会提交。
                    </Typography.Text>
                    <Input.TextArea
                      aria-label="完整声明式模板"
                      value={json}
                      rows={16}
                      className="code-input"
                      onChange={(event) => {
                        setJson(event.target.value)
                        setJsonPending(true)
                      }}
                    />
                    <Space wrap>
                      <Button onClick={applyJson} disabled={!jsonPending || submitting}>
                        校验并应用 JSON
                      </Button>
                      <Button
                        disabled={!jsonPending || submitting}
                        onClick={() => {
                          setJson(JSON.stringify(form.getFieldValue('manifest'), null, 2))
                          setJsonPending(false)
                          setError(null)
                        }}
                      >
                        放弃 JSON 修改
                      </Button>
                    </Space>
                  </Space>
                ),
              },
              ...(base
                ? [
                    {
                      key: 'diff',
                      label: `与 v${base.version} 差异（${changes.length}）`,
                      children: (
                        <Table
                          rowKey="path"
                          size="small"
                          dataSource={changes}
                          pagination={false}
                          scroll={{ x: 640 }}
                          locale={{ emptyText: '配置与原版本相同' }}
                          columns={[
                            { title: '字段', dataIndex: 'path' },
                            { title: '原版本', dataIndex: 'before' },
                            { title: '当前表单', dataIndex: 'after' },
                          ]}
                        />
                      ),
                    },
                  ]
                : []),
            ]}
          />
        </Form>
      </Modal>
    </>
  )
}
function errorText(error: unknown): string {
  return error instanceof Error ? error.message : '请检查模板配置'
}
type ManifestDifference = { path: string; before: string; after: string }
function manifestDifferences(before: unknown, after: unknown): ManifestDifference[] {
  function flatten(value: unknown, prefix = ''): Map<string, string> {
    if (value && typeof value === 'object')
      return new Map(
        Object.entries(value).flatMap(([key, child]) => [
          ...flatten(child, prefix ? `${prefix}.${key}` : key),
        ]),
      )
    return new Map([[prefix, JSON.stringify(value) ?? '未设置']])
  }
  const oldFields = flatten(before),
    newFields = flatten(after)
  return [...new Set([...oldFields.keys(), ...newFields.keys()])]
    .filter((key) => oldFields.get(key) !== newFields.get(key))
    .map((path) => ({
      path,
      before: oldFields.get(path) ?? '未设置',
      after: newFields.get(path) ?? '未设置',
    }))
}
function TemplateDraftProtection({ dirty }: { dirty: boolean }) {
  const dataRouter = useContext(UNSAFE_DataRouterContext)
  useEffect(() => {
    if (!dirty) return
    const block = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', block)
    return () => window.removeEventListener('beforeunload', block)
  }, [dirty])
  return dataRouter ? <TemplateNavigationGuard dirty={dirty} /> : null
}
function TemplateNavigationGuard({ dirty }: { dirty: boolean }) {
  const blocker = useBlocker(dirty)
  return (
    <Modal
      open={blocker.state === 'blocked'}
      title="模板修改尚未保存"
      okText="放弃修改并离开"
      cancelText="继续编辑"
      onOk={() => blocker.proceed?.()}
      onCancel={() => blocker.reset?.()}
    >
      离开将放弃此模板的表单和未应用的JSON修改。
    </Modal>
  )
}
