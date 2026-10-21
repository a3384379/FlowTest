import { Alert, App, Button, Col, Form, Input, Modal, Row, Space, Table, Tabs } from 'antd'
import type { NamePath } from 'antd/es/form/interface'
import { useContext, useEffect, useState } from 'react'
import { UNSAFE_DataRouterContext, useBlocker } from 'react-router-dom'
import type { PerformanceScenario, PerformanceScenarioInput } from './performance-service'
import {
  defaultPerformanceDraft,
  draftDefinition,
  parsePerformanceDefinition,
  performanceDraft,
  PerformanceFieldError,
  validatePerformanceDefinition,
  type PerformanceForm,
} from './performance-definition'
import PerformanceDefinitionFields from './PerformanceDefinitionFields'
import './performance-editor.css'
export default function PerformanceScenarioDialog({
  base,
  submitting,
  onClose,
  onSubmit,
}: {
  base?: PerformanceScenario
  submitting: boolean
  onClose: () => void
  onSubmit: (input: PerformanceScenarioInput) => Promise<boolean>
}) {
  const [form] = Form.useForm<PerformanceForm>()
  const [initial] = useState<PerformanceForm>(() => initialPerformanceForm(base))
  const [dirty, setDirty] = useState(false),
    [json, setJson] = useState(''),
    [jsonPending, setJsonPending] = useState(false),
    [error, setError] = useState<string | null>(null),
    [tab, setTab] = useState('form')
  const draft = Form.useWatch((value: PerformanceForm) => value.definition, {
    form,
    preserve: true,
  })
  const changes = versionChanges(base, initial.definition, draft)
  const { modal } = App.useApp()
  function changed() {
    setDirty(JSON.stringify(form.getFieldsValue(true)) !== JSON.stringify(initial))
    setError(null)
  }
  function close() {
    if (submitting) return
    if (!dirty && !jsonPending) {
      onClose()
      return
    }
    modal.confirm({
      title: '性能配置尚未保存',
      content: '关闭将放弃当前表单和未应用的JSON修改。',
      okText: '放弃修改',
      cancelText: '继续编辑',
      onOk: onClose,
    })
  }
  function exportJson() {
    if (jsonPending) return
    try {
      setJson(JSON.stringify(draftDefinition(form.getFieldValue('definition')), null, 2))
      setTab('json')
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }
  function applyJson() {
    try {
      form.setFieldValue('definition', performanceDraft(parsePerformanceDefinition(json)))
      setJsonPending(false)
      changed()
      setTab('form')
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }
  async function submit() {
    if (jsonPending) {
      setError('高级JSON尚未应用，请先应用或放弃JSON修改')
      return
    }
    try {
      const values = form.getFieldsValue(true) as PerformanceForm
      const definition = validatePerformanceDefinition(draftDefinition(values.definition))
      if (await onSubmit({ name: values.name, description: values.description, definition })) {
        setDirty(false)
        onClose()
      }
    } catch (caught) {
      if (caught instanceof PerformanceFieldError)
        form.setFields([
          {
            name: ['definition', ...caught.path] as NamePath<PerformanceForm>,
            errors: [caught.message],
          },
        ])
      setError(errorMessage(caught))
      setTab('form')
    }
  }
  return (
    <>
      <PerformanceDraftProtection dirty={dirty || jsonPending} />
      <Modal
        open
        title={base ? `${base.name} · 从 v${base.version} 创建新版本` : '新建声明式性能场景'}
        width={1040}
        onCancel={close}
        onOk={() => form.submit()}
        confirmLoading={submitting}
        cancelButtonProps={{ disabled: submitting }}
        closable={!submitting}
        mask={{ closable: !submitting }}
        keyboard={!submitting}
        destroyOnHidden
        className="performance-scenario-dialog"
      >
        <Alert
          type="info"
          title={base ? `基于固定v${base.version} · ${base.id}` : '保存为草稿，审阅发布后才能运行'}
          description="保存不启动压测；原版本和历史运行的冻结配置保持。只接受声明式HTTP配置。"
        />
        {error && (
          <Alert
            type="error"
            showIcon
            title="性能配置尚未提交"
            description={`配置校验失败：${error}`}
          />
        )}
        <Form
          form={form}
          name="performance-scenario-editor"
          layout="vertical"
          initialValues={initial}
          disabled={submitting}
          onValuesChange={changed}
          onFinish={() => void submit()}
        >
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item name="name" label="场景名称" rules={[{ required: true }]}>
                <Input maxLength={160} disabled={Boolean(base)} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item name="description" label={base ? '版本说明' : '说明'}>
                <Input maxLength={2000} />
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
                children: <PerformanceDefinitionFields />,
              },
              {
                key: 'json',
                label: '高级 JSON',
                forceRender: true,
                children: (
                  <Space orientation="vertical" className="performance-field-stack">
                    <Alert
                      type="info"
                      title="JSON通过同一合同校验后显式应用；未应用的修改不会提交。"
                    />
                    <Input.TextArea
                      aria-label="完整声明式配置"
                      value={json}
                      rows={16}
                      className="code-input"
                      onChange={(event) => {
                        setJson(event.target.value)
                        setJsonPending(true)
                      }}
                    />
                    <Space wrap>
                      <Button disabled={!jsonPending || submitting} onClick={applyJson}>
                        校验并应用 JSON
                      </Button>
                      <Button
                        disabled={!jsonPending || submitting}
                        onClick={() => {
                          setJson('')
                          setJsonPending(false)
                          setTab('form')
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
                          locale={{ emptyText: '表单配置与原版本相同' }}
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
function versionChanges(
  base: PerformanceScenario | undefined,
  initial: PerformanceForm['definition'],
  draft: PerformanceForm['definition'] | undefined,
): Difference[] {
  return base ? definitionDifferences(initial, draft ?? initial) : []
}
function initialPerformanceForm(base?: PerformanceScenario): PerformanceForm {
  return {
    name: base?.name ?? '',
    description: base?.description ?? '',
    definition: base ? performanceDraft(base.definition) : defaultPerformanceDraft(),
  }
}
function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '请检查性能配置'
}
type Difference = { path: string; before: string; after: string }
function definitionDifferences(before: unknown, after: unknown): Difference[] {
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
function PerformanceDraftProtection({ dirty }: { dirty: boolean }) {
  const dataRouter = useContext(UNSAFE_DataRouterContext)
  useEffect(() => {
    if (!dirty) return
    const block = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', block)
    return () => window.removeEventListener('beforeunload', block)
  }, [dirty])
  return dataRouter ? <PerformanceNavigationGuard dirty={dirty} /> : null
}
function PerformanceNavigationGuard({ dirty }: { dirty: boolean }) {
  const blocker = useBlocker(dirty)
  return (
    <Modal
      open={blocker.state === 'blocked'}
      title="性能配置尚未保存"
      okText="放弃修改并离开"
      cancelText="继续编辑"
      onOk={() => blocker.proceed?.()}
      onCancel={() => blocker.reset?.()}
    >
      离开将放弃当前表单和未应用的JSON修改。
    </Modal>
  )
}
