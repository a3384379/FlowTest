import {
  CloudServerOutlined,
  DeleteOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Empty,
  Spin,
  Tabs,
  Timeline,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'

import type {
  EnvironmentInstance,
  EnvironmentTemplateInput,
  EnvironmentTemplateManifest,
  EnvironmentTemplateVersion,
} from '../features/environments/environment-service'
import { apiErrorMessage } from '../lib/api'
import ResponseCodeReader from '../features/api-console/ResponseCodeReader'
import { useEnvironmentLab } from '../features/environments/use-environment-lab'

type TemplateForm = {
  template_key: string
  display_name: string
  description: string
  image: string
  internal_port: number
  health_kind: 'http' | 'tcp'
  health_path: string
  seed_enabled: boolean
  seed_path: string
  default_ttl_seconds: number
  maximum_ttl_seconds: number
  cpu_millicores: number
  memory_megabytes: number
  pids_limit: number
  user_id: number
  group_id: number
}

type ProvisionForm = { template_version_id: string; ttl_seconds: number }

export default function EnvironmentLabPage() {
  const state = useEnvironmentLab()
  const [templateDialog, setTemplateDialog] = useState<
    { mode: 'register' } | { mode: 'version'; template: EnvironmentTemplateVersion } | null
  >(null)
  const templates = state.templates.data?.items ?? []
  const instances = state.instances.data?.items ?? []
  return (
    <>
      <div className="page-heading">
        <div>
          <Space align="center">
            <Typography.Title level={2}>环境实验室</Typography.Title>
            <Tag color="cyan">V3 · S26</Tag>
          </Space>
          <Typography.Text type="secondary">
            由管理员签名版本化模板，使用镜像白名单和独立 Runner 按需 Provision、健康检查、Seed
            与幂等清理。
          </Typography.Text>
        </div>
        {state.isSystemAdmin ? (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setTemplateDialog({ mode: 'register' })}
          >
            注册环境模板
          </Button>
        ) : null}
      </div>
      <Alert
        showIcon
        type="info"
        className="page-alert"
        title="仅接受平台声明式模板"
        description="禁止上传任意 Compose、命令、脚本和卷挂载；所有镜像必须固定 Digest 并进入管理员白名单。"
      />
      <EnvironmentOverview totalTemplates={state.templates.data?.total} instances={instances} />
      <ProvisionCard
        templates={templates.filter((item) => item.status === 'active')}
        disabled={!state.canEdit}
        submitting={state.provisioning}
        onProvision={state.startProvision}
      />
      <EnvironmentReadErrors state={state} />
      <div className="lab-workspace">
        <div className="lab-catalogs">
          <Card
            title="已签名环境模板"
            loading={state.templates.isLoading}
            className="performance-card"
          >
            <TemplateTable
              templates={templates}
              page={state.templatePage}
              total={state.templates.data?.total}
              onPage={state.setTemplatePage}
              isSystemAdmin={state.isSystemAdmin}
              pending={state.templateMutationPending}
              onVersion={(template) => setTemplateDialog({ mode: 'version', template })}
              onDisable={state.disableTemplate}
            />
          </Card>
          <Card
            title="环境实例与清理"
            loading={state.instances.isLoading}
            className="performance-card"
          >
            <InstanceTable
              instances={instances}
              page={state.instancePage}
              total={state.instances.data?.total}
              onPage={state.setInstancePage}
              disabled={!state.canEdit}
              onSelect={state.selectInstance}
              cleaning={state.cleaning}
              onCleanup={state.startCleanup}
            />
          </Card>
        </div>
        <EnvironmentInstanceWorkspace state={state} />
      </div>
      {isVersionDialog(templateDialog) ? (
        <TemplateVersionDialog
          key={templateDialog.template.id}
          template={templateDialog.template}
          submitting={state.templateMutationPending}
          onClose={() => setTemplateDialog(null)}
          onSubmit={async (manifest) => {
            if (await state.addVersion(templateDialog.template.template_id, manifest))
              setTemplateDialog(null)
          }}
        />
      ) : (
        <TemplateDialog
          state={templateDialog}
          submitting={state.templateMutationPending}
          onClose={() => setTemplateDialog(null)}
          onSubmit={async (input) => {
            const succeeded = await state.registerTemplate(input)
            if (succeeded) setTemplateDialog(null)
          }}
        />
      )}
    </>
  )
}

function EnvironmentOverview({
  totalTemplates,
  instances,
}: {
  totalTemplates: number | undefined
  instances: EnvironmentInstance[]
}) {
  return (
    <Row gutter={16} className="performance-overview">
      <Col span={8}>
        <Card>
          <Statistic
            title="签名模板版本"
            value={totalTemplates ?? '未提供'}
            prefix={<SafetyCertificateOutlined />}
          />
        </Card>
      </Col>
      <Col span={8}>
        <Card>
          <Statistic
            title="本页就绪实例"
            value={instances.filter((item) => item.status === 'ready').length}
            prefix={<CloudServerOutlined />}
          />
        </Card>
      </Col>
      <Col span={8}>
        <Card>
          <Statistic
            title="本页已完成清理"
            value={instances.filter((item) => item.cleanup_status === 'completed').length}
          />
        </Card>
      </Col>
    </Row>
  )
}

function ProvisionCard({
  templates,
  disabled,
  submitting,
  onProvision,
}: {
  templates: EnvironmentTemplateVersion[]
  disabled: boolean
  submitting: boolean
  onProvision: (templateVersionId: string, ttlSeconds: number) => Promise<boolean>
}) {
  const [form] = Form.useForm<ProvisionForm>()
  return (
    <Card title="Provision 受控环境" className="performance-card">
      <Form
        className="environment-provision-form"
        form={form}
        layout="inline"
        initialValues={{ ttl_seconds: 3600 }}
        onFinish={(value) => void onProvision(value.template_version_id, value.ttl_seconds)}
      >
        <Form.Item
          name="template_version_id"
          label="模板版本"
          rules={[{ required: true, message: '请选择模板版本' }]}
        >
          <Select
            aria-label="模板版本"
            className="environment-template-select"
            placeholder="选择管理员签名模板"
            options={templates.map((item) => ({
              value: item.id,
              label: `${item.display_name} · v${item.version}`,
            }))}
          />
        </Form.Item>
        <Form.Item name="ttl_seconds" label="TTL（秒）" rules={[{ required: true }]}>
          <InputNumber min={60} max={86400} />
        </Form.Item>
        <Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            disabled={disabled || templates.length === 0}
            loading={submitting}
          >
            Provision
          </Button>
        </Form.Item>
      </Form>
    </Card>
  )
}

function TemplateTable({
  page,
  total,
  onPage,
  templates,
  isSystemAdmin,
  pending,
  onVersion,
  onDisable,
}: {
  page: number
  total: number | undefined
  onPage: (page: number) => void
  templates: EnvironmentTemplateVersion[]
  isSystemAdmin: boolean
  pending: boolean
  onVersion: (template: EnvironmentTemplateVersion) => void
  onDisable: (templateId: string) => Promise<void>
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={{ current: page, pageSize: 20, total, showSizeChanger: false, onChange: onPage }}
      dataSource={templates}
      locale={{ emptyText: '暂无管理员签名环境模板' }}
      expandable={{ expandedRowRender: (item) => <TemplateEvidence template={item} /> }}
      columns={[
        { title: '模板', dataIndex: 'display_name' },
        { title: '标识', dataIndex: 'template_key' },
        { title: '版本', dataIndex: 'version', width: 80, render: (value) => `v${value}` },
        { title: '镜像数', render: (_, item) => item.manifest.services.length },
        {
          title: '状态',
          dataIndex: 'status',
          render: (value) => (
            <Tag color={value === 'active' ? 'success' : 'default'}>
              {value === 'active' ? '可用' : '已停用'}
            </Tag>
          ),
        },
        ...(isSystemAdmin
          ? [
              {
                title: '管理员操作',
                width: 180,
                render: (_: unknown, item: EnvironmentTemplateVersion) => (
                  <Space>
                    <Button
                      type="link"
                      disabled={item.status !== 'active'}
                      onClick={() => onVersion(item)}
                    >
                      新建版本
                    </Button>
                    <Popconfirm
                      title="停用后不能再 Provision 或创建版本，确认吗？"
                      onConfirm={() => void onDisable(item.template_id)}
                    >
                      <Button type="link" danger disabled={pending || item.status !== 'active'}>
                        停用
                      </Button>
                    </Popconfirm>
                  </Space>
                ),
              },
            ]
          : []),
      ]}
    />
  )
}

function TemplateEvidence({ template }: { template: EnvironmentTemplateVersion }) {
  return (
    <Descriptions size="small" column={2} bordered>
      <Descriptions.Item label="Manifest SHA-256">{template.manifest_sha256}</Descriptions.Item>
      <Descriptions.Item label="签名算法">{template.signature_algorithm}</Descriptions.Item>
      <Descriptions.Item label="固定镜像" span={2}>
        {template.manifest.services.map((service) => (
          <Typography.Text code key={service.name}>
            {service.image}
          </Typography.Text>
        ))}
      </Descriptions.Item>
      <Descriptions.Item label="TTL">
        {template.manifest.default_ttl_seconds} / {template.manifest.maximum_ttl_seconds} 秒
      </Descriptions.Item>
      <Descriptions.Item label="安全边界">
        只读根文件系统 · Drop ALL · No New Privileges
      </Descriptions.Item>
    </Descriptions>
  )
}

function InstanceTable({
  page,
  total,
  onPage,
  disabled,
  onSelect,
  instances,
  cleaning,
  onCleanup,
}: {
  page: number
  total: number | undefined
  onPage: (page: number) => void
  disabled: boolean
  onSelect: (id: string) => void
  instances: EnvironmentInstance[]
  cleaning: boolean
  onCleanup: (instanceId: string) => Promise<void>
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={{ current: page, pageSize: 20, total, showSizeChanger: false, onChange: onPage }}
      dataSource={instances}
      locale={{ emptyText: '暂无环境实例' }}
      expandable={{ expandedRowRender: (item) => <InstanceEvidence instance={item} /> }}
      columns={[
        {
          title: '实例',
          render: (_, row) => (
            <Button type="link" onClick={() => onSelect(row.id)}>
              {row.id.slice(0, 8)}
            </Button>
          ),
        },
        { title: '模板', render: (_, item) => `${item.template_key} · v${item.template_version}` },
        { title: '状态', dataIndex: 'status', render: (value) => <InstanceStatus value={value} /> },
        { title: '清理', dataIndex: 'cleanup_status', render: cleanupStatus },
        { title: 'TTL', dataIndex: 'ttl_seconds', render: (value) => `${value} 秒` },
        {
          title: '操作',
          render: (_, item) => (
            <Popconfirm
              title={`确认取消实例 ${item.id}（${item.template_key} · v${item.template_version}）并执行幂等清理？`}
              onConfirm={() => void onCleanup(item.id)}
            >
              <Button
                type="link"
                danger
                icon={<DeleteOutlined />}
                loading={cleaning}
                disabled={disabled || item.cleanup_status === 'completed'}
              >
                清理
              </Button>
            </Popconfirm>
          ),
        },
      ]}
    />
  )
}

function InstanceEvidence({ instance }: { instance: EnvironmentInstance }) {
  return (
    <Descriptions size="small" column={2} bordered>
      <Descriptions.Item label="Runtime">{instance.runtime_name}</Descriptions.Item>
      <Descriptions.Item label="Fencing Token">{instance.fencing_token}</Descriptions.Item>
      <Descriptions.Item label="到期时间">
        {new Date(instance.expires_at).toLocaleString()}
      </Descriptions.Item>
      <Descriptions.Item label="清理次数">{instance.cleanup_attempts}</Descriptions.Item>
      <Descriptions.Item label="端点" span={2}>
        {instance.endpoints.length > 0
          ? instance.endpoints.map((endpoint) => `${endpoint.service}: ${endpoint.url}`).join('；')
          : '此实例尚未提供端点'}
      </Descriptions.Item>
      {instance.error_message ? (
        <Descriptions.Item label="失败原因" span={2}>
          {instance.error_code} · {instance.error_message}
        </Descriptions.Item>
      ) : null}
    </Descriptions>
  )
}

function InstanceStatus({ value }: { value: EnvironmentInstance['status'] }) {
  const labels: Record<EnvironmentInstance['status'], string> = {
    queued: '排队中',
    provisioning: 'Provision 中',
    ready: '已就绪',
    failed: '失败',
    cancelled: '已取消',
    expired: '已过期',
    cleaned: '已清理',
  }
  const color =
    value === 'ready'
      ? 'success'
      : value === 'failed'
        ? 'error'
        : value === 'provisioning'
          ? 'processing'
          : 'default'
  return <Tag color={color}>{labels[value]}</Tag>
}

function cleanupStatus(value: EnvironmentInstance['cleanup_status']) {
  const labels = {
    none: '未触发',
    pending: '等待中',
    running: '清理中',
    completed: '已完成',
    failed: '需重试',
  }
  return labels[value]
}

function TemplateDialog({
  state,
  submitting,
  onClose,
  onSubmit,
}: {
  state: { mode: 'register' } | { mode: 'version'; template: EnvironmentTemplateVersion } | null
  submitting: boolean
  onClose: () => void
  onSubmit: (input: EnvironmentTemplateInput) => Promise<void>
}) {
  const [form] = Form.useForm<TemplateForm>()
  const base = state?.mode === 'version' ? state.template : undefined
  const healthKind = Form.useWatch('health_kind', form) ?? 'http'
  return (
    <Modal
      title={base ? `为 ${base.display_name} 创建签名版本` : '注册管理员签名环境模板'}
      open={state !== null}
      width={820}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        key={base?.id ?? 'register'}
        form={form}
        layout="vertical"
        initialValues={templateFormValues(base)}
        onFinish={(value) => void onSubmit(toTemplateInput(value))}
      >
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="template_key" label="模板标识" rules={[{ required: true }]}>
              <Input disabled={Boolean(base)} placeholder="platform.web" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="display_name" label="显示名称" rules={[{ required: true }]}>
              <Input disabled={Boolean(base)} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="description" label="说明">
              <Input disabled={Boolean(base)} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="image" label="白名单镜像（必须固定 Digest）" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Row gutter={16}>
          <Col span={6}>
            <Form.Item name="internal_port" label="服务端口">
              <InputNumber min={1024} max={65535} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="health_kind" label="健康检查">
              <Select
                options={[
                  { value: 'http', label: 'HTTP' },
                  { value: 'tcp', label: 'TCP' },
                ]}
              />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item
              name="health_path"
              label="健康路径"
              rules={healthKind === 'http' ? [{ required: true }] : []}
            >
              <Input disabled={healthKind === 'tcp'} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="seed_enabled" label="预定义 Seed" valuePropName="checked">
              <Checkbox>HTTP GET v1</Checkbox>
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col span={6}>
            <Form.Item name="default_ttl_seconds" label="默认 TTL">
              <InputNumber min={60} max={86400} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="maximum_ttl_seconds" label="最大 TTL">
              <InputNumber min={60} max={86400} />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name="cpu_millicores" label="CPU (m)">
              <InputNumber min={100} max={2000} />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name="memory_megabytes" label="内存 (MiB)">
              <InputNumber min={64} max={2048} />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name="pids_limit" label="PID 上限">
              <InputNumber min={16} max={256} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col span={6}>
            <Form.Item name="user_id" label="容器 UID">
              <InputNumber min={1} max={65535} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="group_id" label="容器 GID">
              <InputNumber min={1} max={65535} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="seed_path" label="Seed 路径">
              <Input />
            </Form.Item>
          </Col>
        </Row>
        <Typography.Text type="secondary">
          Compose、命令、脚本、Secret 与卷字段不在模板契约中；安全加固标志由平台固定开启。
        </Typography.Text>
      </Form>
    </Modal>
  )
}

const fixtureImage =
  'cgr.dev/chainguard/nginx@sha256:a104d1995e56b7a15e8f152078dfbdb1ecbf9f9d1af311e7906e7b4c0c790cf2'

function templateFormValues(base?: EnvironmentTemplateVersion): TemplateForm {
  return base ? versionFormValues(base) : defaultTemplateFormValues
}

const defaultTemplateFormValues: TemplateForm = {
  template_key: 'platform.web',
  display_name: '受控 Web 环境',
  description: '',
  image: fixtureImage,
  internal_port: 8080,
  health_kind: 'http',
  health_path: '/',
  seed_enabled: true,
  seed_path: '/',
  default_ttl_seconds: 3600,
  maximum_ttl_seconds: 14400,
  cpu_millicores: 250,
  memory_megabytes: 128,
  pids_limit: 64,
  user_id: 65532,
  group_id: 65532,
}

function versionFormValues(base: EnvironmentTemplateVersion): TemplateForm {
  const service = base.manifest.services[0]
  const seed = base.manifest.seeds[0]
  return {
    template_key: base.template_key,
    display_name: base.display_name,
    description: base.description,
    image: service.image,
    internal_port: service.internal_port,
    health_kind: service.health_check.kind,
    health_path: service.health_check.path ?? '/',
    seed_enabled: base.manifest.seeds.length > 0,
    seed_path: seed?.path ?? '/',
    default_ttl_seconds: base.manifest.default_ttl_seconds,
    maximum_ttl_seconds: base.manifest.maximum_ttl_seconds,
    cpu_millicores: service.cpu_millicores,
    memory_megabytes: service.memory_megabytes,
    pids_limit: service.pids_limit,
    user_id: service.user_id,
    group_id: service.group_id,
  }
}

function toTemplateInput(value: TemplateForm): EnvironmentTemplateInput {
  const manifest: EnvironmentTemplateManifest = {
    services: [
      {
        name: 'web',
        image: value.image,
        internal_port: value.internal_port,
        environment: [{ name: 'NGINX_PORT', value: String(value.internal_port) }],
        depends_on: [],
        health_check: {
          kind: value.health_kind,
          path: value.health_kind === 'http' ? value.health_path : null,
          expected_status: 200,
          interval_seconds: 1,
          timeout_seconds: 2,
          maximum_attempts: 30,
        },
        cpu_millicores: value.cpu_millicores,
        memory_megabytes: value.memory_megabytes,
        pids_limit: value.pids_limit,
        user_id: value.user_id,
        group_id: value.group_id,
        read_only_root_filesystem: true,
        drop_all_capabilities: true,
        no_new_privileges: true,
      },
    ],
    seeds: value.seed_enabled
      ? [{ profile: 'http_get_v1', service: 'web', path: value.seed_path }]
      : [],
    default_ttl_seconds: value.default_ttl_seconds,
    maximum_ttl_seconds: value.maximum_ttl_seconds,
  }
  return {
    template_key: value.template_key,
    display_name: value.display_name,
    description: value.description,
    manifest,
  }
}

function EnvironmentReadErrors({ state }: { state: ReturnType<typeof useEnvironmentLab> }) {
  return (
    <>
      {[
        { query: state.templates, name: '模板目录' },
        { query: state.instances, name: '实例目录' },
        { query: state.permissions, name: '项目权限' },
      ]
        .filter((read) => read.query.isError)
        .map((read) => (
          <Alert
            key={read.name}
            type="error"
            showIcon
            title={`${read.name}读取失败`}
            description={apiErrorMessage(read.query.error)}
            action={<Button onClick={() => void read.query.refetch()}>重试</Button>}
          />
        ))}
    </>
  )
}

function EnvironmentInstanceWorkspace({ state }: { state: ReturnType<typeof useEnvironmentLab> }) {
  if (!state.instanceId)
    return (
      <Card className="lab-detail" title="环境实例工作区">
        <Empty description="选择实例查看生命周期、端点、Seed 和清理证据" />
      </Card>
    )
  if (state.instance.isError)
    return (
      <Card className="lab-detail">
        <Alert
          showIcon
          type="error"
          title="实例读取失败"
          description={apiErrorMessage(state.instance.error)}
          action={<Button onClick={() => void state.instance.refetch()}>重试</Button>}
        />
      </Card>
    )
  if (state.instance.isPending)
    return (
      <Card className="lab-detail">
        <Spin aria-label="正在读取实例" />
      </Card>
    )
  if (state.instance.data.project_id !== state.projectId)
    return (
      <Card className="lab-detail">
        <Alert type="error" title="实例不属于当前项目" />
      </Card>
    )
  const instance = state.instance.data
  const template = state.templates.data?.items.find(
    (item) => item.id === instance.template_version_id,
  )
  return (
    <Card className="lab-detail" title="环境实例 · 生命周期">
      <Space wrap>
        <InstanceStatus value={instance.status} />
        <Tag>
          {instance.template_key} · v{instance.template_version}
        </Tag>
        <Typography.Text>{instance.id}</Typography.Text>
      </Space>
      <InstanceEvidence instance={instance} />
      <Alert type="info" title="状态来自实例生命周期记录；当前接口未提供持续服务健康采样。" />
      <Tabs
        items={[
          {
            key: 'lifecycle',
            label: '生命周期与清理',
            children: <InstanceLifecycle instance={instance} />,
          },
          {
            key: 'seed',
            label: 'Seed 证据',
            children: instance.seed_evidence.length ? (
              <Table
                rowKey={(row) => `${row.service}:${row.path}`}
                pagination={false}
                size="small"
                dataSource={instance.seed_evidence}
                columns={[
                  { title: '服务', dataIndex: 'service' },
                  { title: '预定义任务', dataIndex: 'profile' },
                  { title: '路径', dataIndex: 'path' },
                  { title: '实际状态码', dataIndex: 'status_code' },
                ]}
              />
            ) : (
              <Empty description="此实例没有 Seed 执行证据" />
            ),
          },
          {
            key: 'resources',
            label: '签名配置与资源',
            children: template ? (
              <>
                <TemplateEvidence template={template} />
                <ResponseCodeReader value={template.manifest} title="此实例绑定的签名模板配置" />
              </>
            ) : (
              <Alert
                type="info"
                title="当前模板页未提供此实例绑定的版本；切换模板目录页查看，实例记录不会替换为其他版本。"
              />
            ),
          },
        ]}
      />
    </Card>
  )
}

function InstanceLifecycle({ instance }: { instance: EnvironmentInstance }) {
  const milestones = [
    { name: '进入队列', time: instance.queued_at },
    { name: '开始 Provision', time: instance.started_at },
    { name: '就绪', time: instance.ready_at },
    { name: '到期', time: instance.expires_at },
    { name: '请求取消', time: instance.cancellation_requested_at },
    { name: '开始清理', time: instance.cleanup_started_at },
    { name: '完成清理', time: instance.cleaned_at },
  ]
  return (
    <>
      <Timeline
        items={milestones.map((item) => ({
          color: item.time ? 'blue' : 'gray',
          title: item.name,
          content: item.time ?? '尚未发生',
        }))}
      />
      <Descriptions column={1} size="small">
        <Descriptions.Item label="清理状态">
          {cleanupStatus(instance.cleanup_status)}
        </Descriptions.Item>
        <Descriptions.Item label="清理次数">{instance.cleanup_attempts}</Descriptions.Item>
        <Descriptions.Item label="清理失败代码">
          {instance.cleanup_error_code ?? '未提供'}
        </Descriptions.Item>
        <Descriptions.Item label="最近记录更新">{instance.updated_at}</Descriptions.Item>
      </Descriptions>
    </>
  )
}

function TemplateVersionDialog({
  template,
  submitting,
  onClose,
  onSubmit,
}: {
  template: EnvironmentTemplateVersion
  submitting: boolean
  onClose: () => void
  onSubmit: (manifest: EnvironmentTemplateManifest) => Promise<void>
}) {
  const [form] = Form.useForm<{ manifest: string }>()
  return (
    <Modal
      title={`为 ${template.display_name} 创建签名版本`}
      open
      width={900}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ manifest: JSON.stringify(template.manifest, null, 2) }}
        onFinish={(value) => void onSubmit(parseEnvironmentManifest(value.manifest))}
      >
        <Alert
          type="info"
          title={`完整保留 v${template.version} 的全部服务、依赖、健康检查、资源与 Seed；提交后由服务端校验并签名。`}
        />
        <Form.Item
          name="manifest"
          label="完整声明式模板"
          rules={[
            { required: true },
            {
              validator: async (_, value: string) => {
                parseEnvironmentManifest(value)
              },
            },
          ]}
          extra="仅接受受控模板字段；镜像必须固定 Digest。"
        >
          <Input.TextArea rows={18} className="code-input" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function parseEnvironmentManifest(text: string): EnvironmentTemplateManifest {
  let value: EnvironmentTemplateManifest
  try {
    value = JSON.parse(text) as EnvironmentTemplateManifest
  } catch {
    throw new Error('请输入有效的声明式 JSON 模板')
  }
  if (
    !value ||
    !Array.isArray(value.services) ||
    !value.services.length ||
    !Array.isArray(value.seeds)
  )
    throw new Error('模板需包含服务和 Seed 列表')
  return value
}

function isVersionDialog(
  state: { mode: 'register' } | { mode: 'version'; template: EnvironmentTemplateVersion } | null,
): state is { mode: 'version'; template: EnvironmentTemplateVersion } {
  return state?.mode === 'version'
}
