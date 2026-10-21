import FeatureDisabledNotice from '../components/FeatureDisabledNotice'
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
  Col,
  Descriptions,
  Input,
  Empty,
  Spin,
  Tabs,
  Timeline,
  Popconfirm,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'

import type {
  EnvironmentInstance,
  EnvironmentTemplateVersion,
} from '../features/environments/environment-service'
import { apiErrorWithTrace } from '../lib/api'
import { useRouteScopedState } from '../lib/use-route-scoped-state'
import EnvironmentTemplateDialog from '../features/environments/EnvironmentTemplateDialog'
import EnvironmentProvisionCard from '../features/environments/EnvironmentProvisionCard'
import ResponseCodeReader from '../features/api-console/ResponseCodeReader'
import { useEnvironmentLab } from '../features/environments/use-environment-lab'

export default function EnvironmentLabPage() {
  const state = useEnvironmentLab()
  const [templateDialog, setTemplateDialog] = useRouteScopedState<
    { mode: 'register' } | { mode: 'version'; template: EnvironmentTemplateVersion } | null
  >(state.projectId, null, null)
  const templates = state.templates.data?.items ?? []
  const instances = state.instances.data?.items ?? []
  return (
    <>
      <FeatureDisabledNotice
        flags={state.featureFlags.data}
        feature="environment_lab"
        label="环境实验室"
      />
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
      <EnvironmentOverview
        totalTemplates={state.templates.data?.total}
        instances={instanceRows(state.instances.data)}
      />
      <EnvironmentProvisionCard
        key={state.projectId}
        projectId={state.projectId}
        enabled={state.featureEnabled}
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
            <Input.Search
              aria-label="查找签名模板"
              placeholder="按名称、标识或说明查找"
              onSearch={state.setTemplateSearch}
            />
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
      <TemplateEditor
        state={state}
        dialog={templateDialog}
        onClose={() => setTemplateDialog(null)}
      />
    </>
  )
}

function TemplateEditor({
  state,
  dialog,
  onClose,
}: {
  state: ReturnType<typeof useEnvironmentLab>
  dialog: { mode: 'register' } | { mode: 'version'; template: EnvironmentTemplateVersion } | null
  onClose: () => void
}) {
  if (!dialog) return null
  const base = dialog.mode === 'version' ? dialog.template : undefined
  return (
    <EnvironmentTemplateDialog
      key={`${state.projectId}:${base?.id ?? 'register'}`}
      base={base}
      submitting={state.templateMutationPending}
      onClose={onClose}
      onSubmit={(input) =>
        base ? state.addVersion(base.template_id, input.manifest) : state.registerTemplate(input)
      }
    />
  )
}

function EnvironmentOverview({
  totalTemplates,
  instances,
}: {
  totalTemplates: number | undefined
  instances: EnvironmentInstance[] | undefined
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
            value={instances?.filter((item) => item.status === 'ready').length ?? '—'}
            prefix={<CloudServerOutlined />}
          />
        </Card>
      </Col>
      <Col span={8}>
        <Card>
          <Statistic
            title="本页已完成清理"
            value={instances?.filter((item) => item.cleanup_status === 'completed').length ?? '—'}
          />
        </Card>
      </Col>
    </Row>
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
      scroll={{ x: 680 }}
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
    <Descriptions size="small" column={{ xs: 1, sm: 2 }} bordered>
      <Descriptions.Item label="Manifest SHA-256">
        <Typography.Text copyable>{template.manifest_sha256}</Typography.Text>
      </Descriptions.Item>
      <Descriptions.Item label="签名算法">{template.signature_algorithm}</Descriptions.Item>
      <Descriptions.Item label="固定镜像" span={2}>
        <Space orientation="vertical">
          {template.manifest.services.map((service) => (
            <Typography.Text code key={service.name}>
              {service.name}: {service.image}
            </Typography.Text>
          ))}
        </Space>
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
      scroll={{ x: 650 }}
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
    <Descriptions size="small" column={{ xs: 1, sm: 2 }} bordered>
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

function EnvironmentReadErrors({ state }: { state: ReturnType<typeof useEnvironmentLab> }) {
  return (
    <>
      {[
        { query: state.templates, name: '模板目录' },
        { query: state.instances, name: '实例目录' },
        { query: state.permissions, name: '项目权限' },
        { query: state.featureFlags, name: '模块能力' },
      ]
        .filter((read) => read.query.isError)
        .map((read) => (
          <Alert
            key={read.name}
            type="error"
            showIcon
            title={`${read.name}读取失败`}
            description={apiErrorWithTrace(read.query.error)}
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
          description={apiErrorWithTrace(state.instance.error)}
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
            children: <BoundTemplate state={state} instance={instance} />,
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

function BoundTemplate({
  state,
  instance,
}: {
  state: ReturnType<typeof useEnvironmentLab>
  instance: EnvironmentInstance
}) {
  const query = state.boundTemplate
  return (
    <div className="environment-bound-template">
      <Typography.Paragraph>
        固定模板版本ID：{instance.template_version_id} · {instance.template_key} · v
        {instance.template_version}
      </Typography.Paragraph>
      {query.isError ? (
        <Alert
          type="error"
          showIcon
          title="绑定模板读取失败"
          description={apiErrorWithTrace(query.error)}
          action={<Button onClick={() => void query.refetch()}>重试绑定版本</Button>}
        />
      ) : query.isPending ? (
        <Spin aria-label="正在读取绑定模板" />
      ) : (
        <>
          {query.data.status === 'disabled' && (
            <Alert
              type="warning"
              title="模板已停用；此处保留实例绑定的原始签名版本，不能再次Provision"
            />
          )}
          <TemplateEvidence template={query.data} />
          <ResponseCodeReader value={query.data.manifest} title="此实例绑定的签名模板配置" />
        </>
      )}
    </div>
  )
}

function instanceRows(
  data: { items: EnvironmentInstance[] } | undefined,
): EnvironmentInstance[] | undefined {
  return data?.items
}
