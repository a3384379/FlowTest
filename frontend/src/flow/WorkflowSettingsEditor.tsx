import { DeleteOutlined, PlusOutlined, SettingOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Switch,
  Typography,
} from 'antd'
import { useState } from 'react'
import type { WorkflowDefinition } from '../lib/api'

type SettingsProps = {
  definition: WorkflowDefinition
  editable: boolean
  historical: boolean
  beforeOpen: () => Promise<boolean>
  onChange: (definition: WorkflowDefinition) => void
}

export default function WorkflowSettingsEditor(props: SettingsProps) {
  const [open, setOpen] = useState(false)
  async function show() {
    if (await props.beforeOpen()) setOpen(true)
  }
  return (
    <>
      <Button aria-label="流程设置" icon={<SettingOutlined />} onClick={() => void show()}>
        流程设置
      </Button>
      <Drawer
        title={props.historical ? '流程设置 · 冻结快照' : '流程设置'}
        size={440}
        open={open}
        onClose={() => setOpen(false)}
        footer={
          <Button aria-label="关闭流程设置" onClick={() => setOpen(false)}>
            关闭
          </Button>
        }
      >
        <Alert
          type="info"
          showIcon
          title={props.editable ? '更改直接应用到图草稿' : '流程设置只读'}
          description={
            props.editable
              ? '可以撤销或重做；保存草稿后持久化。设置修改不会触发发布或执行。'
              : '这里展示当前定义的配置；历史模式使用当次执行的冻结快照。'
          }
        />
        <ExecutionSettings {...props} />
        <WorkflowVariables {...props} />
      </Drawer>
    </>
  )
}

function ExecutionSettings({ definition, editable, onChange }: SettingsProps) {
  function change(settings: Partial<WorkflowDefinition['settings']>) {
    if (editable) onChange({ ...definition, settings: { ...definition.settings, ...settings } })
  }
  return (
    <section className="workflow-settings-section">
      <Typography.Title level={5}>执行设置</Typography.Title>
      <Form layout="vertical">
        <Form.Item
          label="并发上限"
          htmlFor="workflow-concurrency"
          extra="1–100，限制流程调度并发。"
        >
          <InputNumber
            id="workflow-concurrency"
            value={definition.settings.concurrency}
            disabled={!editable}
            min={1}
            max={100}
            precision={0}
            onChange={(value) => {
              if (validInteger(value, 100)) change({ concurrency: value })
            }}
          />
        </Form.Item>
        <Form.Item
          label="默认超时（秒）"
          htmlFor="workflow-timeout"
          extra="1–300 秒，沿用现有执行契约。"
        >
          <InputNumber
            id="workflow-timeout"
            value={definition.settings.default_timeout_seconds}
            disabled={!editable}
            min={1}
            max={300}
            precision={0}
            onChange={(value) => {
              if (validInteger(value, 300)) change({ default_timeout_seconds: value })
            }}
          />
        </Form.Item>
        <Form.Item label="失败即停止" htmlFor="workflow-fail-fast">
          <Switch
            id="workflow-fail-fast"
            checked={definition.settings.fail_fast}
            disabled={!editable}
            onChange={(value) => change({ fail_fast: value })}
          />
        </Form.Item>
      </Form>
    </section>
  )
}

function validInteger(value: number | null, maximum: number): value is number {
  return value !== null && Number.isInteger(value) && value >= 1 && value <= maximum
}

function WorkflowVariables(props: SettingsProps) {
  const { definition, editable, onChange } = props
  function change(name: string, value: string) {
    if (editable) onChange({ ...definition, variables: { ...definition.variables, [name]: value } })
  }
  function remove(name: string) {
    if (!editable) return
    const variables = Object.fromEntries(
      Object.entries(definition.variables).filter(([key]) => key !== name),
    )
    onChange({ ...definition, variables })
  }
  return (
    <section className="workflow-settings-section">
      <Typography.Title level={5}>流程初始变量</Typography.Title>
      <Typography.Paragraph type="secondary">
        值按字符串保存。变量属于流程定义，执行时的实际变量值在运行证据中查看。
      </Typography.Paragraph>
      {Object.entries(definition.variables).map(([name, value]) => (
        <div key={name} className="workflow-variable-row">
          <Typography.Text code>{name}</Typography.Text>
          <Input.TextArea
            aria-label={`变量 ${name} 的初始值`}
            value={value}
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={!editable}
            onChange={(event) => change(name, event.target.value)}
          />
          {editable && (
            <Popconfirm
              title={`删除变量 ${name}？`}
              description="删除会应用到图草稿，可撤销。"
              okText="删除"
              okButtonProps={{ 'aria-label': '确认删除变量' }}
              cancelText="取消"
              onConfirm={() => remove(name)}
            >
              <Button danger aria-label={`删除变量 ${name}`} icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </div>
      ))}
      {!Object.keys(definition.variables).length && (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无流程初始变量" />
      )}
      {editable && <NewWorkflowVariable variables={definition.variables} onAdd={change} />}
    </section>
  )
}

function NewWorkflowVariable({
  variables,
  onAdd,
}: {
  variables: WorkflowDefinition['variables']
  onAdd: (name: string, value: string) => void
}) {
  const [form] = Form.useForm<{ name: string; value: string }>()
  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={{ name: '', value: '' }}
      onFinish={({ name, value }) => {
        onAdd(name, value)
        form.resetFields()
      }}
    >
      <Form.Item
        label="新变量名"
        name="name"
        rules={[
          { required: true, message: '请输入变量名' },
          {
            pattern: /^[A-Za-z_][A-Za-z0-9_.-]*$/,
            max: 160,
            message: '使用字母或下划线开头，包含字母、数字、点、横线或下划线，最多 160 字符',
          },
          {
            validator: (_, value: string) =>
              Object.hasOwn(variables, value)
                ? Promise.reject(new Error('变量名已存在'))
                : Promise.resolve(),
          },
        ]}
      >
        <Input />
      </Form.Item>
      <Form.Item label="新变量初始值" name="value">
        <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} />
      </Form.Item>
      <Button aria-label="添加变量" htmlType="submit" icon={<PlusOutlined />}>
        添加变量
      </Button>
      <Typography.Paragraph type="secondary">新变量在点击添加后进入图草稿。</Typography.Paragraph>
    </Form>
  )
}
