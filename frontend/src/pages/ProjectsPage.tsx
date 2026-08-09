import { SafetyCertificateOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  type FormInstance,
} from 'antd'
import { useEffect } from 'react'

import AccessManagementPanel from '../features/projects/AccessManagementPanel'
import AssetManagementPanel from '../features/projects/AssetManagementPanel'
import {
  getProjectPermission,
  getProjectRetentionPolicy,
  getProjectSecurityPolicy,
  listProjectAuditLogs,
  updateProjectSecurityPolicy,
  updateProjectRetentionPolicy,
} from '../features/projects/project-service'
import { useProjectContext } from '../features/projects/use-project-context'
import {
  apiErrorMessage,
  type AuditLog,
  type ProjectCapability,
  type ProjectPermission,
  type ProjectRetentionPolicy,
  type ProjectSecurityPolicy,
} from '../lib/api'

const capabilityLabels: Record<ProjectCapability, string> = {
  read: '查看',
  edit: '编辑',
  execute: '执行',
  manage_members: '成员管理',
  manage_security: '安全策略',
  view_audit: '审计日志',
}

const roleLabels = {
  system_admin: '系统管理员',
  owner: '项目 Owner',
  editor: 'Editor',
  viewer: 'Viewer',
}

type PolicyForm = { allowed_hosts: string; allowed_private_cidrs: string }

export default function ProjectsPage() {
  const state = useProjectsPageState()
  if (!state.projectsLoading && !state.projectId) {
    return <Empty description="暂无可访问项目" />
  }
  return <ProjectsView state={state} />
}

function useProjectsPageState() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projects, projectId, selectProject } = useProjectContext()
  const [form] = Form.useForm<PolicyForm>()
  const permission = useQuery({
    queryKey: ['project-permissions', projectId],
    queryFn: () => getProjectPermission(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const policy = useQuery({
    queryKey: ['project-security-policy', projectId],
    queryFn: () => getProjectSecurityPolicy(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const retention = useQuery({
    queryKey: ['project-retention-policy', projectId],
    queryFn: () => getProjectRetentionPolicy(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const canManageSecurity = hasCapability(permission.data, 'manage_security')
  const canManageMembers = hasCapability(permission.data, 'manage_members')
  const canEdit = hasCapability(permission.data, 'edit')
  const canViewAudit = hasCapability(permission.data, 'view_audit')
  const audit = useQuery({
    queryKey: ['project-audit', projectId],
    queryFn: () => listProjectAuditLogs(requiredId(projectId)),
    enabled: Boolean(projectId) && canViewAudit,
  })

  useEffect(() => synchronizePolicyForm(form, policy.data), [form, policy.data])

  const updatePolicy = useMutation({
    mutationFn: (value: ProjectSecurityPolicy) =>
      updateProjectSecurityPolicy(requiredId(projectId), value),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['project-security-policy', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['project-audit', projectId] }),
      ])
      void message.success('出站安全策略已保存')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const updateRetention = useMutation({
    mutationFn: (days: number) => updateProjectRetentionPolicy(requiredId(projectId), days),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['project-retention-policy', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['project-audit', projectId] }),
      ])
      void message.success('数据保留策略已保存')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  return {
    projectId,
    projects: projects.data?.items ?? [],
    projectsLoading: projects.isLoading,
    setSelection: selectProject,
    permission: permission.data,
    permissionLoading: permission.isLoading,
    policyLoading: policy.isLoading,
    form,
    canManageSecurity,
    canManageMembers,
    canEdit,
    updatePolicy: (values: PolicyForm) => updatePolicy.mutate(policyPayload(values)),
    updatePolicyPending: updatePolicy.isPending,
    retention: retention.data,
    retentionLoading: retention.isLoading,
    updateRetention: (days: number) => updateRetention.mutate(days),
    updateRetentionPending: updateRetention.isPending,
    canViewAudit,
    audit: audit.data?.items ?? [],
    auditLoading: audit.isLoading,
  }
}

type ProjectsPageState = ReturnType<typeof useProjectsPageState>

function ProjectsView({ state }: { state: ProjectsPageState }) {
  return (
    <>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>项目治理</Typography.Title>
          <Typography.Text type="secondary">
            查看固定权限矩阵，维护出站访问白名单并追踪不可变审计记录。
          </Typography.Text>
        </div>
        <Select
          aria-label="治理项目"
          className="context-select"
          loading={state.projectsLoading}
          value={state.projectId}
          onChange={state.setSelection}
          options={state.projects.map((item) => ({ value: item.id, label: item.name }))}
        />
      </div>
      <Row gutter={[16, 16]}>
        <PermissionPanel data={state.permission} loading={state.permissionLoading} />
        <SecurityPolicyPanel
          form={state.form}
          loading={state.policyLoading}
          canManage={state.canManageSecurity}
          saving={state.updatePolicyPending}
          onSave={state.updatePolicy}
        />
        <RetentionPolicyPanel
          policy={state.retention}
          loading={state.retentionLoading}
          canManage={state.canManageSecurity}
          saving={state.updateRetentionPending}
          onSave={state.updateRetention}
        />
        {state.projectId && (
          <Col span={24}>
            <AccessManagementPanel projectId={state.projectId} canManage={state.canManageMembers} />
          </Col>
        )}
        {state.projectId && (
          <Col span={24}>
            <AssetManagementPanel projectId={state.projectId} canEdit={state.canEdit} />
          </Col>
        )}
        <AuditPanel visible={state.canViewAudit} loading={state.auditLoading} items={state.audit} />
      </Row>
    </>
  )
}

function RetentionPolicyPanel({
  policy,
  loading,
  canManage,
  saving,
  onSave,
}: {
  policy?: ProjectRetentionPolicy
  loading: boolean
  canManage: boolean
  saving: boolean
  onSave: (days: number) => void
}) {
  const [form] = Form.useForm<{ retention_days: number }>()
  useEffect(() => {
    if (policy) form.setFieldsValue({ retention_days: policy.retention_days })
  }, [form, policy])
  return (
    <Col xs={24} xl={10}>
      <Card title="数据保留策略" loading={loading}>
        <Typography.Paragraph type="secondary">
          执行、报告与附件到期后由每日清理任务删除；审计记录不随项目保留期清理。
        </Typography.Paragraph>
        <Form form={form} layout="inline" onFinish={(values) => onSave(values.retention_days)}>
          <Form.Item
            label="保留天数"
            name="retention_days"
            rules={[{ required: true, message: '请输入保留天数' }]}
          >
            <InputNumber min={1} max={policy?.maximum_days ?? 3650} disabled={!canManage} />
          </Form.Item>
          <Button htmlType="submit" type="primary" disabled={!canManage} loading={saving}>
            保存保留策略
          </Button>
        </Form>
      </Card>
    </Col>
  )
}

function PermissionPanel({ data, loading }: { data?: ProjectPermission; loading: boolean }) {
  return (
    <Col xs={24} xl={10}>
      <Card title="权限矩阵" loading={loading}>
        {data && (
          <>
            <Alert
              type="info"
              showIcon
              title={`当前身份：${roleLabels[data.effective_role]}`}
              description={data.capabilities.map((item) => capabilityLabels[item]).join('、')}
            />
            <Table
              className="governance-table"
              rowKey="role"
              size="small"
              pagination={false}
              dataSource={Object.entries(data.matrix).map(([role, capabilities]) => ({
                role,
                capabilities,
              }))}
              columns={[
                {
                  title: '角色',
                  dataIndex: 'role',
                  width: 120,
                  render: (role: 'owner' | 'editor' | 'viewer') => roleLabels[role],
                },
                {
                  title: '能力',
                  dataIndex: 'capabilities',
                  render: (items: ProjectCapability[]) => <CapabilityTags items={items} />,
                },
              ]}
            />
          </>
        )}
      </Card>
    </Col>
  )
}

function CapabilityTags({ items }: { items: ProjectCapability[] }) {
  return (
    <Space size={[0, 4]} wrap>
      {items.map((item) => (
        <Tag key={item}>{capabilityLabels[item]}</Tag>
      ))}
    </Space>
  )
}

function SecurityPolicyPanel({
  form,
  loading,
  canManage,
  saving,
  onSave,
}: {
  form: FormInstance<PolicyForm>
  loading: boolean
  canManage: boolean
  saving: boolean
  onSave: (values: PolicyForm) => void
}) {
  return (
    <Col xs={24} xl={14}>
      <Card
        title={
          <Space>
            <SafetyCertificateOutlined />
            出站请求安全策略
          </Space>
        }
        loading={loading}
      >
        <Alert
          type="warning"
          showIcon
          title="默认阻止私网、回环、链路本地和云元数据地址"
          description="公共地址默认可访问；填写域名后将启用域名白名单。私网目标还必须同时命中允许 CIDR，DNS 解析后的每个地址都会重新校验。"
        />
        <Form form={form} layout="vertical" className="governance-policy-form" onFinish={onSave}>
          <Form.Item label="允许域名（每行一个）" name="allowed_hosts">
            <Input.TextArea rows={4} readOnly={!canManage} />
          </Form.Item>
          <Form.Item label="允许私网 CIDR（每行一个）" name="allowed_private_cidrs">
            <Input.TextArea rows={3} readOnly={!canManage} />
          </Form.Item>
          <Button htmlType="submit" type="primary" disabled={!canManage} loading={saving}>
            保存安全策略
          </Button>
        </Form>
      </Card>
    </Col>
  )
}

function AuditPanel({
  visible,
  loading,
  items,
}: {
  visible: boolean
  loading: boolean
  items: AuditLog[]
}) {
  if (!visible) return null
  return (
    <Col span={24}>
      <Card title="审计日志">
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          pagination={false}
          dataSource={items}
          columns={[
            {
              title: '时间',
              dataIndex: 'created_at',
              width: 180,
              render: (value: string) => new Date(value).toLocaleString('zh-CN'),
            },
            { title: '操作', dataIndex: 'action', width: 240 },
            { title: '资源', dataIndex: 'resource_type', width: 160 },
            {
              title: 'Trace ID',
              render: (_, item) => String(item.details.trace_id ?? '-'),
            },
          ]}
        />
      </Card>
    </Col>
  )
}

function synchronizePolicyForm(form: FormInstance<PolicyForm>, policy?: ProjectSecurityPolicy) {
  if (!policy) return
  form.setFieldsValue({
    allowed_hosts: policy.allowed_hosts.join('\n'),
    allowed_private_cidrs: policy.allowed_private_cidrs.join('\n'),
  })
}

function hasCapability(data: ProjectPermission | undefined, capability: ProjectCapability) {
  return Boolean(data?.capabilities.includes(capability))
}

function policyPayload(values: PolicyForm): ProjectSecurityPolicy {
  return {
    allowed_hosts: splitLines(values.allowed_hosts),
    allowed_private_cidrs: splitLines(values.allowed_private_cidrs),
  }
}

function splitLines(value = ''): string[] {
  return [
    ...new Set(
      value
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ]
}

function requiredId(value: string | null): string {
  if (!value) throw new Error('缺少项目标识')
  return value
}
