import { DeleteOutlined, PlusOutlined, SaveOutlined } from '@ant-design/icons'
import {
  App,
  Alert,
  Button,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import type { Environment } from '../../lib/api'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { listRequestServices } from '../service-targets/service-target-service'
import type { CreateEnvironmentInput, UpdateEnvironmentInput } from './api-service'
import EnvironmentMapEditor from './EnvironmentMapEditor'
import { mapValue, parseEnvironmentMap, type EnvironmentMapValue } from './environment-map'
import EnvironmentEndpoints from './EnvironmentEndpoints'

type EnvironmentForm = {
  name: string
  base_url: string
  default_service_id: string | null
  variables: EnvironmentMapValue
  headers: EnvironmentMapValue
}
type Props = {
  projectId: string
  environments: Environment[]
  catalogFailed?: boolean
  sendingEnvironmentId: string | null
  editable: boolean
  canUse: boolean
  saving: boolean
  deleting: boolean
  onClose: () => void
  onCreate: (input: CreateEnvironmentInput) => Promise<Environment>
  onSave: (id: string, input: UpdateEnvironmentInput) => Promise<Environment>
  onDelete: (id: string) => Promise<void>
  onUse: (id: string) => void
}

export default function EnvironmentManager(props: Props) {
  const { modal } = App.useApp()
  const [editingId, setEditingId] = useState<string | null>(() =>
    initialEditingId(props.environments, props.sendingEnvironmentId),
  )
  const [dirty, setDirty] = useState(false)
  const [epoch, setEpoch] = useState(0)
  const [operationPending, setOperationPending] = useState(false)
  const busy = props.saving || props.deleting || operationPending
  const environment = props.environments.find((item) => item.id === editingId)
  const services = useQuery({
    queryKey: ['request-services', props.projectId],
    queryFn: () => listRequestServices(props.projectId),
  })
  function guard(action: () => void) {
    if (busy) return
    if (!dirty) {
      action()
      return
    }
    modal.confirm({
      title: '环境配置尚未保存',
      content: '离开会丢弃当前修改。',
      okText: '丢弃修改并继续',
      cancelText: '继续编辑',
      onOk: () => {
        setDirty(false)
        action()
      },
    })
  }
  async function save(values: EnvironmentForm) {
    setOperationPending(true)
    try {
      const input = {
        name: values.name.trim(),
        base_url: values.base_url.trim(),
        variables: parseEnvironmentMap(values.variables, 'variables'),
        headers: parseEnvironmentMap(values.headers, 'headers'),
      }
      const saved = environment
        ? await props.onSave(environment.id, {
            ...input,
            default_service_id: values.default_service_id ?? null,
          })
        : await props.onCreate(input)
      setEditingId(saved.id)
      setDirty(false)
      setEpoch((value) => value + 1)
    } finally {
      setOperationPending(false)
    }
  }
  async function remove(id: string) {
    setOperationPending(true)
    try {
      await props.onDelete(id)
      setEditingId(props.environments.find((item) => item.id !== id)?.id ?? null)
      setDirty(false)
    } finally {
      setOperationPending(false)
    }
  }
  function applyEnvironment(id: string) {
    guard(() => {
      setEpoch((value) => value + 1)
      props.onUse(id)
    })
  }
  return (
    <Drawer
      open
      title="管理环境"
      size={880}
      rootClassName="environment-manager-drawer"
      closable={!busy}
      maskClosable={!busy}
      keyboard={!busy}
      onClose={() => guard(props.onClose)}
    >
      <div className="environment-manager-layout">
        <nav className="environment-manager-list" aria-label="项目环境列表">
          <Button
            block
            icon={<PlusOutlined />}
            disabled={!props.editable || busy}
            onClick={() =>
              guard(() => {
                setEditingId(null)
                setEpoch((value) => value + 1)
              })
            }
          >
            新建环境
          </Button>
          {props.environments.map((item) => (
            <Button
              key={item.id}
              block
              type={editingId === item.id ? 'primary' : 'text'}
              disabled={busy}
              aria-label={`编辑环境 ${item.name}`}
              aria-pressed={editingId === item.id}
              onClick={() => {
                if (item.id !== editingId) guard(() => setEditingId(item.id))
              }}
            >
              {item.name}
              {props.sendingEnvironmentId === item.id && <Tag>发送中</Tag>}
            </Button>
          ))}
        </nav>
        <div className="environment-manager-detail">
          <QueryFailureNotice queries={[services]} />
          <EnvironmentFormStatus catalogFailed={props.catalogFailed} editable={props.editable} />
          <Typography.Title level={4}>
            {environment?.name ?? '新建环境'}
            {dirty && <Tag color="orange">未保存</Tag>}
          </Typography.Title>
          <Typography.Paragraph type="secondary">
            正在编辑的环境与发送环境独立；保存配置不会切换发送目标。
          </Typography.Paragraph>
          <EnvironmentEditorBoundary
            missing={unavailableEnvironment(editingId, environment)}
            key={`${editingId}:${epoch}`}
            environment={environment}
            editable={props.editable}
            busy={busy}
            services={services.data ?? []}
            onSave={save}
            onDirty={setDirty}
            endpointPanel={
              environment ? (
                <EnvironmentEndpoints
                  projectId={props.projectId}
                  environmentId={environment.id}
                  editable={props.editable && !busy}
                />
              ) : (
                <Alert type="info" title="保存环境后可配置各模块的服务地址。" />
              )
            }
            actions={
              <EnvironmentActions
                environment={environment}
                editable={props.editable}
                canUse={props.canUse}
                busy={busy}
                onUse={applyEnvironment}
                onDelete={remove}
              />
            }
          />
        </div>
      </div>
    </Drawer>
  )
}

function EnvironmentActions({
  environment,
  editable,
  canUse,
  busy,
  onUse,
  onDelete,
}: {
  environment?: Environment
  editable: boolean
  canUse: boolean
  busy: boolean
  onUse: (id: string) => void
  onDelete: (id: string) => Promise<void>
}) {
  if (!environment) return null
  return (
    <Space wrap>
      <Button disabled={!canUse || busy} onClick={() => onUse(environment.id)}>
        用此环境调试
      </Button>
      <Popconfirm
        title={`删除环境「${environment.name}」？`}
        description="历史执行和快照会保留，环境将不再用于新执行。"
        okText="删除"
        cancelText="取消"
        onConfirm={() => onDelete(environment.id)}
        disabled={!editable || busy}
      >
        <Button danger icon={<DeleteOutlined />} disabled={!editable || busy}>
          删除环境
        </Button>
      </Popconfirm>
    </Space>
  )
}

function EnvironmentFormStatus({
  catalogFailed,
  editable,
}: {
  catalogFailed?: boolean
  editable: boolean
}) {
  return (
    <>
      {catalogFailed && <Alert type="warning" title="环境列表暂时无法刷新，当前修改已保留。" />}
      {!editable && <Alert type="info" title="当前权限只允许查看环境配置。" />}
    </>
  )
}

function unavailableEnvironment(id: string | null, environment?: Environment): boolean {
  return id !== null && !environment
}
function EnvironmentEditorBoundary(
  props: React.ComponentProps<typeof EnvironmentEditor> & { missing: boolean },
) {
  if (props.missing)
    return <Alert type="warning" title="正在编辑的环境已失效，请选择其他环境或新建环境。" />
  return <EnvironmentEditor {...props} />
}

function EnvironmentEditor({
  environment,
  editable,
  busy,
  services,
  onSave,
  onDirty,
  endpointPanel,
  actions,
}: {
  environment?: Environment
  editable: boolean
  busy: boolean
  services: Array<{ id: string; name: string; enabled: boolean }>
  onSave: (values: EnvironmentForm) => Promise<void>
  onDirty: (value: boolean) => void
  endpointPanel: React.ReactNode
  actions: React.ReactNode
}) {
  const [form] = Form.useForm<EnvironmentForm>()
  const initial = environmentValues(environment)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState('basic')
  async function submit(values: EnvironmentForm) {
    if (!editable || busy) return
    try {
      await onSave(values)
      setError('')
    } catch {
      setError('保存失败，修改已保留，请修正后重试。')
    }
  }
  return (
    <Form
      form={form}
      name="environment-config"
      initialValues={initial}
      layout="vertical"
      disabled={!editable || busy}
      onValuesChange={(_, values) => onDirty(formSignature(values) !== formSignature(initial))}
      onFinish={(values) => void submit(values)}
      onFinishFailed={({ errorFields }) =>
        setActiveTab(
          ['variables', 'headers'].includes(String(errorFields[0]?.name[0])) ? 'maps' : 'basic',
        )
      }
    >
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'basic',
            label: '基本信息',
            forceRender: true,
            children: (
              <>
                <Form.Item
                  name="name"
                  label="名称"
                  rules={[
                    {
                      required: true,
                      whitespace: true,
                      max: 160,
                      message: '请输入环境名称（最多 160 字）',
                    },
                  ]}
                >
                  <Input />
                </Form.Item>
                <Form.Item
                  name="base_url"
                  label="默认地址"
                  rules={[
                    { required: true, message: '请输入完整的 HTTP 或 HTTPS 地址' },
                    { validator: validateHttpAddress },
                  ]}
                >
                  <Input placeholder="https://example.test" />
                </Form.Item>
                <Form.Item name="default_service_id" label="默认服务">
                  <Select
                    aria-label="环境默认服务"
                    allowClear
                    disabled={!editable || busy || !environment}
                    onClear={() => form.setFieldValue('default_service_id', null)}
                    options={services.map((item) => ({
                      value: item.id,
                      label: item.name,
                      disabled: !item.enabled,
                    }))}
                  />
                </Form.Item>
                {!environment && (
                  <Typography.Paragraph type="secondary">
                    新建环境时会配置默认服务，保存后可调整。
                  </Typography.Paragraph>
                )}
              </>
            ),
          },
          {
            key: 'maps',
            label: '变量与请求头',
            forceRender: true,
            children: (
              <>
                <Form.Item name="variables" label="环境变量" rules={[mapRule('variables')]}>
                  <EnvironmentMapEditor kind="variables" readOnly={!editable || busy} />
                </Form.Item>
                <Form.Item name="headers" label="环境请求头" rules={[mapRule('headers')]}>
                  <EnvironmentMapEditor kind="headers" readOnly={!editable || busy} />
                </Form.Item>
                <Typography.Paragraph type="secondary">
                  敏感凭据请在项目的密钥管理中配置。
                </Typography.Paragraph>
              </>
            ),
          },
          { key: 'endpoints', label: '服务地址', children: endpointPanel },
        ]}
      />
      {error && <Alert type="error" title={error} />}
      <Space wrap className="environment-manager-actions">
        <Button
          type="primary"
          htmlType="submit"
          icon={<SaveOutlined />}
          loading={busy}
          disabled={!editable}
        >
          {environment ? '保存配置' : '创建环境'}
        </Button>
        {actions}
      </Space>
    </Form>
  )
}

function initialEditingId(items: Environment[], sendingId: string | null): string | null {
  return items.find((item) => item.id === sendingId)?.id ?? items[0]?.id ?? null
}
function environmentValues(environment?: Environment): EnvironmentForm {
  if (!environment)
    return {
      name: '',
      base_url: '',
      default_service_id: null,
      variables: mapValue({}),
      headers: mapValue({}),
    }
  return {
    name: environment.name,
    base_url: environment.base_url,
    default_service_id: environment.default_service_id ?? null,
    variables: mapValue(environment.variables),
    headers: mapValue(environment.headers),
  }
}

function mapRule(kind: 'variables' | 'headers') {
  return {
    validator: async (_: unknown, value: EnvironmentMapValue) => {
      parseEnvironmentMap(value, kind)
    },
  }
}
function formSignature(values: EnvironmentForm): string {
  try {
    return JSON.stringify([
      values.name,
      values.base_url,
      values.default_service_id ?? null,
      sortedEntries(parseEnvironmentMap(values.variables, 'variables')),
      sortedEntries(parseEnvironmentMap(values.headers, 'headers')),
    ])
  } catch {
    return JSON.stringify(values)
  }
}
function sortedEntries(values: Record<string, string>) {
  return Object.entries(values).sort(([a], [b]) => a.localeCompare(b))
}
async function validateHttpAddress(_: unknown, value: string) {
  if (!value) return
  try {
    const parsed = new URL(value)
    if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname) throw new Error()
  } catch {
    throw new Error('请输入完整的 HTTP 或 HTTPS 地址')
  }
}
