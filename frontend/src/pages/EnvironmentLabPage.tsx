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
      <EnvironmentOverview templates={templates} instances={instances} />
      <ProvisionCard
        templates={templates.filter((item) => item.status === 'active')}
        disabled={!state.projectId}
        submitting={state.provisioning}
        onProvision={state.startProvision}
      />
      <Card title="已签名环境模板" loading={state.templates.isLoading} className="performance-card">
        <TemplateTable
          templates={templates}
          isSystemAdmin={state.isSystemAdmin}
          pending={state.templateMutationPending}
          onVersion={(template) => setTemplateDialog({ mode: 'version', template })}
          onDisable={state.disableTemplate}
        />
      </Card>
      <Card title="环境实例与清理" loading={state.instances.isLoading} className="performance-card">
        <InstanceTable
          instances={instances}
          cleaning={state.cleaning}
          onCleanup={state.startCleanup}
        />
      </Card>
      <TemplateDialog
        state={templateDialog}
        submitting={state.templateMutationPending}
        onClose={() => setTemplateDialog(null)}
        onSubmit={async (input) => {
          const succeeded =
            templateDialog?.mode === 'version'
              ? await state.addVersion(templateDialog.template.template_id, input.manifest)
              : await state.registerTemplate(input)
          if (succeeded) setTemplateDialog(null)
        }}
      />
    </>
  )
}

function EnvironmentOverview({
  templates,
  instances,
}: {
  templates: EnvironmentTemplateVersion[]
  instances: EnvironmentInstance[]
}) {
  return (
    <Row gutter={16} className="performance-overview">
      <Col span={8}>
        <Card>
          <Statistic
            title="签名模板版本"
            value={templates.length}
            prefix={<SafetyCertificateOutlined />}
          />
        </Card>
      </Col>
      <Col span={8}>
        <Card>
          <Statistic
            title="就绪实例"
            value={instances.filter((item) => item.status === 'ready').length}
            prefix={<CloudServerOutlined />}
          />
        </Card>
      </Col>
      <Col span={8}>
        <Card>
          <Statistic
            title="已完成清理"
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
            style={{ width: 300 }}
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
  templates,
  isSystemAdmin,
  pending,
  onVersion,
  onDisable,
}: {
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
      pagination={{ pageSize: 8 }}
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
  instances,
  cleaning,
  onCleanup,
}: {
  instances: EnvironmentInstance[]
  cleaning: boolean
  onCleanup: (instanceId: string) => Promise<void>
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={{ pageSize: 8 }}
      dataSource={instances}
      locale={{ emptyText: '暂无环境实例' }}
      expandable={{ expandedRowRender: (item) => <InstanceEvidence instance={item} /> }}
      columns={[
        { title: '实例', dataIndex: 'id', render: (value) => value.slice(0, 8) },
        { title: '模板', render: (_, item) => `${item.template_key} · v${item.template_version}` },
        { title: '状态', dataIndex: 'status', render: (value) => <InstanceStatus value={value} /> },
        { title: '清理', dataIndex: 'cleanup_status', render: cleanupStatus },
        { title: 'TTL', dataIndex: 'ttl_seconds', render: (value) => `${value} 秒` },
        {
          title: '操作',
          render: (_, item) => (
            <Popconfirm
              title="确认取消实例并执行幂等清理？"
              onConfirm={() => void onCleanup(item.id)}
            >
              <Button
                type="link"
                danger
                icon={<DeleteOutlined />}
                loading={cleaning}
                disabled={item.cleanup_status === 'completed'}
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
          : '尚未就绪'}
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
  'nginxinc/nginx-unprivileged:1.31.3-alpine3.24@sha256:334d92979f15aaecd5dd50af5105e1230e2bb70765d45b1e2f964e7c5eda81c3'

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
  user_id: 101,
  group_id: 101,
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
