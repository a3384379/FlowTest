import {
  KeyOutlined,
  LockOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  type FormInstance,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { useAuthStore } from '../features/auth/auth-store'
import {
  applyKeyRotation,
  createOrganization,
  createServiceAccount,
  getOrganizationGovernance,
  getOrganizationSecurity,
  getRunnerGovernance,
  getSupportBundleRedaction,
  listOrganizationMembers,
  listOrganizations,
  listServiceAccounts,
  prepareKeyRotation,
  rollbackKeyRotation,
  revokeServiceAccount,
  rotateServiceAccount,
  updateOrganizationGovernance,
  upsertOrganizationMember,
  type Organization,
  type OrganizationGovernance,
  type OrganizationMember,
  type OrganizationRole,
  type QuotaDimension,
  type QuotaMode,
  type ServiceAccount,
} from '../features/organizations/organization-service'
import DirectoryPicker from '../features/projects/DirectoryPicker'
import { apiErrorWithTrace, SessionBoundaryError, setOrganizationId } from '../lib/api'
import OrganizationAuditPanel from './OrganizationAuditPanel'
import OrganizationQueryBoundary from './OrganizationQueryBoundary'
import { rotationAction, type SecurityKeyVersion } from './organization-governance-rotation'

const quotaDimensions: Array<{ key: QuotaDimension; label: string; unit?: string }> = [
  { key: 'project_count', label: '项目数' },
  { key: 'user_count', label: '成员数' },
  { key: 'runner_concurrency', label: 'Runner 并发' },
  { key: 'execution_concurrency', label: '执行并发' },
  { key: 'ai_request_count', label: 'AI 请求（日）' },
  { key: 'artifact_storage', label: 'Artifact 存储', unit: 'bytes' },
]
const quotaModes: Array<{ value: QuotaMode; label: string }> = [
  { value: 'observe', label: '观察' },
  { value: 'warn', label: '预警' },
  { value: 'soft_limit', label: '软限制' },
  { value: 'hard_limit', label: '硬限制' },
]
const serviceAccountScopes = [
  'org:read',
  'org:governance',
  'org:audit',
  'project:read',
  'project:write',
  'execution:trigger',
  'artifact:read',
  'runner:read',
  'runner:manage',
  'audit:read',
  'mcp:read',
  'mcp:write',
  'mcp:evidence:write',
  'mcp:flow:propose',
]

type MemberFormValues = { user_id: string; role: OrganizationRole }
type ServiceAccountFormValues = { name: string; account_key: string; scopes: string[] }
type KeyRotationFormValues = { key_reference: string; key_fingerprint: string }
type GovernanceFormValues = {
  audit_retention_days: number
  quota_policies: Record<
    QuotaDimension,
    { mode: QuotaMode; limit: number | null; warn_at: number | null }
  >
  runner_policy: {
    allowed_runner_types: string[]
    allowed_runtimes: string[]
    max_pools: number
    registration_requires_approval: boolean
  }
}
type RunnerGovernanceData = {
  pool_count: number
  runner_count: number
  current_load: number
  capacity: number
  pools: Array<{
    id: string
    name: string
    runner_type: string
    runtime: string
    enabled: boolean
    current_load: number
    max_concurrency: number
    runner_count: number
  }>
}

export default function OrganizationGovernancePage() {
  const user = useAuthStore((state) => state.user)
  const isSystemAdmin = Boolean(user?.is_system_admin)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const organizations = useQuery({ queryKey: ['organizations'], queryFn: listOrganizations })
  const effectiveSelectedId = selectedId ?? organizations.data?.[0]?.id ?? null

  useEffect(() => {
    setOrganizationId(effectiveSelectedId)
    return () => setOrganizationId(null)
  }, [effectiveSelectedId])

  return (
    <OrganizationGovernanceContent
      isSystemAdmin={isSystemAdmin}
      isLoading={organizations.isLoading}
      isError={organizations.isError}
      organizations={organizations.data ?? []}
      selectedId={effectiveSelectedId}
      onSelect={setSelectedId}
    />
  )
}

function OrganizationGovernanceContent({
  isSystemAdmin,
  isLoading,
  isError,
  organizations,
  selectedId,
  onSelect,
}: {
  isSystemAdmin: boolean
  isLoading: boolean
  isError: boolean
  organizations: Organization[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const { message } = App.useApp()
  const actor = useAuthStore((state) => `${state.user?.id}:${state.epoch}`)
  const selected = organizations.find((organization) => organization.id === selectedId) ?? null

  if (isLoading) return <div className="page-loading">加载组织治理...</div>
  if (isError) return <Alert showIcon type="error" title="组织列表加载失败" />
  if (!organizations.length) return <OrganizationGovernanceEmpty isSystemAdmin={isSystemAdmin} />
  if (!selected) return <div className="page-loading">正在选择组织...</div>
  return (
    <OrganizationGovernanceSelected
      key={`${selected.id}:${actor}`}
      isSystemAdmin={isSystemAdmin}
      organizations={organizations}
      selected={selected}
      onSelect={onSelect}
      onMessage={(type, text) => notify(message, type, text)}
    />
  )
}

function OrganizationGovernanceEmpty({ isSystemAdmin }: { isSystemAdmin: boolean }) {
  return (
    <Empty description="暂无可管理组织">
      <OrganizationCreateAction isSystemAdmin={isSystemAdmin} />
    </Empty>
  )
}

function OrganizationGovernanceSelected({
  isSystemAdmin,
  organizations,
  selected,
  onSelect,
  onMessage,
}: {
  isSystemAdmin: boolean
  organizations: Organization[]
  selected: Organization
  onSelect: (id: string) => void
  onMessage: (type: 'success' | 'error', text: string) => void
}) {
  const [issuedToken, setIssuedToken] = useState<string | null>(null)
  const canManage = isSystemAdmin || selected.role === 'owner' || selected.role === 'admin'
  const canRotate = isSystemAdmin || selected.role === 'owner'
  return (
    <>
      <div className="page-heading">
        <div>
          <Space align="center">
            <Typography.Title level={2}>组织治理</Typography.Title>
            <Tag color="purple">V5 · S44</Tag>
          </Space>
          <Typography.Text type="secondary">
            统一管理组织角色、Service Account、配额、Runner 治理、审计保留与密钥生命周期。
          </Typography.Text>
        </div>
        <Space>
          <Select
            aria-label="治理组织"
            value={selected.id}
            onChange={onSelect}
            options={organizations.map((organization) => ({
              value: organization.id,
              label: `${organization.name} · ${organization.slug}`,
            }))}
          />
          <OrganizationCreateAction isSystemAdmin={isSystemAdmin} />
        </Space>
      </div>
      <OrganizationWorkspace
        organization={selected}
        canSearchUsers={isSystemAdmin}
        canManage={canManage}
        canRotate={canRotate}
        issuedToken={issuedToken}
        setIssuedToken={setIssuedToken}
        onMessage={(type, text) => onMessage(type, text)}
      />
    </>
  )
}

function OrganizationCreateAction({ isSystemAdmin }: { isSystemAdmin: boolean }) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const create = useMutation({
    mutationFn: createOrganization,
    onSuccess: async (organization) => {
      setOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['organizations'] })
      void message.success(`${organization.name} 已创建`)
    },
    onError: () => void message.error('组织创建失败'),
  })
  if (!isSystemAdmin) return null
  return (
    <>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
        新建组织
      </Button>
      <CreateOrganizationDialog
        open={open}
        submitting={create.isPending}
        onClose={() => setOpen(false)}
        onCreate={(values) => create.mutate(values)}
      />
    </>
  )
}

function notify(
  message: ReturnType<typeof App.useApp>['message'],
  type: 'success' | 'error',
  text: string,
) {
  if (type === 'success') message.success(text)
  else message.error(text)
}

function OrganizationWorkspace({
  organization,
  canSearchUsers,
  canManage,
  canRotate,
  issuedToken,
  setIssuedToken,
  onMessage,
}: {
  organization: Organization
  canSearchUsers: boolean
  canManage: boolean
  canRotate: boolean
  issuedToken: string | null
  setIssuedToken: (token: string | null) => void
  onMessage: (type: 'success' | 'error', text: string) => void
}) {
  const workspace = useOrganizationWorkspace({ organization, setIssuedToken, onMessage })
  const accountPending =
    workspace.accountMutation.isPending ||
    workspace.rotateMutation.isPending ||
    workspace.revokeMutation.isPending
  const securityPending =
    workspace.prepareMutation.isPending ||
    workspace.applyKeyMutation.isPending ||
    workspace.rollbackKeyMutation.isPending

  return (
    <OrganizationTabs
      organization={organization}
      canSearchUsers={canSearchUsers}
      canManage={canManage}
      canRotate={canRotate}
      issuedToken={issuedToken}
      setIssuedToken={setIssuedToken}
      workspace={workspace}
      accountPending={accountPending}
      securityPending={securityPending}
    />
  )
}

function OrganizationTabs({
  organization,
  canSearchUsers,
  canManage,
  canRotate,
  issuedToken,
  setIssuedToken,
  workspace,
  accountPending,
  securityPending,
}: {
  organization: Organization
  canSearchUsers: boolean
  canManage: boolean
  canRotate: boolean
  issuedToken: string | null
  setIssuedToken: (token: string | null) => void
  workspace: ReturnType<typeof useOrganizationWorkspace>
  accountPending: boolean
  securityPending: boolean
}) {
  return (
    <Tabs
      items={[
        {
          key: 'overview',
          label: (
            <Space>
              <TeamOutlined />
              组织与角色
            </Space>
          ),
          children: (
            <OrganizationQueryBoundary label="组织成员" query={workspace.members}>
              {(members) => (
                <OverviewTab
                  organization={organization}
                  members={members}
                  canManage={canManage}
                  canSearchUsers={canSearchUsers}
                  memberError={workspace.memberMutation.error}
                  onMemberChange={async (userId, role) => {
                    try {
                      await workspace.memberMutation.mutateAsync({ userId, role })
                      return true
                    } catch {
                      return false
                    }
                  }}
                  pending={workspace.memberMutation.isPending}
                />
              )}
            </OrganizationQueryBoundary>
          ),
        },
        {
          key: 'accounts',
          label: 'Service Account',
          children: (
            <OrganizationQueryBoundary label="服务账号" query={workspace.accounts}>
              {(accounts) => (
                <ServiceAccountsTab
                  form={workspace.accountForm}
                  accounts={accounts}
                  canManage={canManage}
                  issuedToken={issuedToken}
                  onClearToken={() => setIssuedToken(null)}
                  onCreate={workspace.issueAccount}
                  error={workspace.accountMutation.error}
                  onRotate={(id) => workspace.rotateMutation.mutate(id)}
                  onRevoke={(id) => workspace.revokeMutation.mutate(id)}
                  pending={accountPending}
                />
              )}
            </OrganizationQueryBoundary>
          ),
        },
        {
          key: 'governance',
          label: '配额与 Runner',
          children: (
            <OrganizationQueryBoundary label="组织策略" query={workspace.governance}>
              {(governance) => (
                <GovernanceTab
                  organization={governance}
                  runner={workspace.runner}
                  canManage={
                    canManage && workspace.runner.isSuccess && !workspace.runner.isFetching
                  }
                  pending={workspace.governanceMutation.isPending}
                  onSave={(input) => workspace.governanceMutation.mutate(input)}
                />
              )}
            </OrganizationQueryBoundary>
          ),
        },
        {
          key: 'security',
          label: (
            <Space>
              <LockOutlined />
              审计与安全
            </Space>
          ),
          children: (
            <Space orientation="vertical" size="large" style={{ width: '100%' }}>
              <Row gutter={[16, 16]}>
                <Col xs={24} lg={12}>
                  <OrganizationQueryBoundary label="密钥安全" query={workspace.security}>
                    {(security) => (
                      <KeyRotationCard
                        security={security}
                        canRotate={canRotate}
                        onPrepare={(input) => workspace.prepareMutation.mutate(input)}
                        onApply={(id) => workspace.applyKeyMutation.mutate(id)}
                        onRollback={(id) => workspace.rollbackKeyMutation.mutate(id)}
                        pending={securityPending}
                      />
                    )}
                  </OrganizationQueryBoundary>
                </Col>
                <Col xs={24} lg={12}>
                  <OrganizationQueryBoundary label="支持包" query={workspace.supportBundle}>
                    {(supportBundle) => <SupportBundleCard supportBundle={supportBundle} />}
                  </OrganizationQueryBoundary>
                </Col>
              </Row>
              <OrganizationAuditPanel organizationId={organization.id} />
            </Space>
          ),
        },
      ]}
    />
  )
}

function useOrganizationWorkspace({
  organization,
  setIssuedToken,
  onMessage,
}: {
  organization: Organization
  setIssuedToken: (token: string | null) => void
  onMessage: (type: 'success' | 'error', text: string) => void
}) {
  const queryClient = useQueryClient()
  const [accountForm] = Form.useForm<ServiceAccountFormValues>()
  const active = useRef(true)
  useLayoutEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  const governance = useQuery({
    queryKey: ['organization-governance', organization.id],
    queryFn: () => getOrganizationGovernance(organization.id),
  })
  const members = useQuery({
    queryKey: ['organization-members', organization.id],
    queryFn: () => listOrganizationMembers(organization.id),
  })
  const accounts = useQuery({
    queryKey: ['organization-service-accounts', organization.id],
    queryFn: () => listServiceAccounts(organization.id),
  })
  const runner = useQuery({
    queryKey: ['organization-runner-governance', organization.id],
    queryFn: () => getRunnerGovernance(organization.id),
  })
  const security = useQuery({
    queryKey: ['organization-security', organization.id],
    queryFn: () => getOrganizationSecurity(organization.id),
  })
  const supportBundle = useQuery({
    queryKey: ['organization-support-bundle', organization.id],
    queryFn: () => getSupportBundleRedaction(organization.id),
  })
  const invalidate = async (...keys: string[]) => {
    await Promise.all(
      keys.map((key) => queryClient.invalidateQueries({ queryKey: [key, organization.id] })),
    )
  }
  const memberMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: OrganizationRole }) =>
      upsertOrganizationMember(organization.id, userId, role),
    onSuccess: async () => {
      await Promise.all([
        invalidate('organization-members'),
        queryClient.invalidateQueries({ queryKey: ['organizations'], exact: true }),
      ])
      onMessage('success', '组织角色已更新')
    },
  })
  const accountMutation = useMutation({
    mutationFn: (input: ServiceAccountFormValues) => createServiceAccount(organization.id, input),
    onSuccess: async (issued) => {
      await invalidate('organization-service-accounts')
      if (!active.current) return
      accountForm.resetFields()
      setIssuedToken(issued.token)
      onMessage('success', 'Service Account 已创建，令牌只显示一次')
    },
    onError: (error) => accountFailure(error, 'Service Account 创建失败'),
  })
  const rotateMutation = useMutation({
    mutationFn: (accountId: string) => rotateServiceAccount(organization.id, accountId),
    onSuccess: async (issued) => {
      await invalidate('organization-service-accounts')
      if (!active.current) return
      setIssuedToken(issued.token)
      onMessage('success', 'Service Account 令牌已轮换')
    },
    onError: (error) => accountFailure(error, 'Service Account 轮换失败'),
  })
  const revokeMutation = useMutation({
    mutationFn: (accountId: string) => revokeServiceAccount(organization.id, accountId),
    onSuccess: async () => {
      await invalidate('organization-service-accounts')
      if (active.current) onMessage('success', 'Service Account 已撤销')
    },
    onError: (error) => accountFailure(error, 'Service Account 撤销失败'),
  })
  const governanceMutation = useMutation({
    mutationFn: (input: GovernanceFormValues) =>
      updateOrganizationGovernance(organization.id, input),
    onSuccess: async () => {
      await invalidate('organization-governance', 'organization-runner-governance')
      onMessage('success', '组织治理策略已保存')
    },
    onError: () => onMessage('error', '组织治理策略保存失败'),
  })
  const prepareMutation = useMutation({
    mutationFn: (input: KeyRotationFormValues) => prepareKeyRotation(organization.id, input),
    onSuccess: async () => {
      await invalidate('organization-security')
      onMessage('success', '密钥轮换版本已创建')
    },
    onError: () => onMessage('error', '密钥轮换版本创建失败'),
  })
  const applyKeyMutation = useMutation({
    mutationFn: (keyVersionId: string) => applyKeyRotation(organization.id, keyVersionId),
    onSuccess: async () => {
      await invalidate('organization-security', 'organization-audit')
      onMessage('success', '组织密文已重加密、校验并激活新密钥')
    },
    onError: () => onMessage('error', '密钥轮换 Apply 失败，未激活新版本'),
  })
  const rollbackKeyMutation = useMutation({
    mutationFn: (keyVersionId: string) => rollbackKeyRotation(organization.id, keyVersionId),
    onSuccess: async () => {
      await invalidate('organization-security', 'organization-audit')
      onMessage('success', '组织密文已验证回滚到前一密钥版本')
    },
    onError: () => onMessage('error', '密钥轮换 Rollback 失败'),
  })
  async function accountFailure(error: unknown, text: string): Promise<void> {
    if (error instanceof SessionBoundaryError) {
      await queryClient.invalidateQueries({
        queryKey: ['organization-service-accounts', organization.id],
        refetchType: 'none',
      })
      return
    }
    if (active.current) onMessage('error', text)
  }
  async function issueAccount(input: ServiceAccountFormValues): Promise<boolean> {
    try {
      await accountMutation.mutateAsync(input)
      return active.current
    } catch {
      return false
    }
  }
  return {
    governance,
    members,
    accounts,
    runner,
    security,
    supportBundle,
    memberMutation,
    accountMutation,
    accountForm,
    issueAccount,
    rotateMutation,
    revokeMutation,
    governanceMutation,
    prepareMutation,
    applyKeyMutation,
    rollbackKeyMutation,
  }
}

function OverviewTab({
  organization,
  members,
  canSearchUsers,
  memberError,
  canManage,
  onMemberChange,
  pending,
}: {
  organization: Organization
  members: OrganizationMember[]
  canSearchUsers: boolean
  memberError: Error | null
  canManage: boolean
  onMemberChange: (userId: string, role: OrganizationRole) => Promise<boolean>
  pending: boolean
}) {
  const [form] = Form.useForm<MemberFormValues>()
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={8}>
        <Card title="组织信息">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="名称">{organization.name}</Descriptions.Item>
            <Descriptions.Item label="Slug">{organization.slug}</Descriptions.Item>
            <Descriptions.Item label="当前角色">
              <Tag color="blue">{organization.role ?? 'system_admin'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="成员数">
              {organization.member_count ?? members.length}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              {organization.enabled ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      </Col>
      <Col xs={24} lg={16}>
        <Card title="组织角色" extra={<Tag>{members.length} 人</Tag>}>
          {memberError && (
            <Alert
              showIcon
              type="error"
              title="组织角色更新失败"
              description={apiErrorWithTrace(memberError)}
              className="page-alert"
            />
          )}
          {canManage && (
            <Form
              form={form}
              layout="inline"
              disabled={pending}
              onFinish={async (values) => {
                if (pending) return
                if (await onMemberChange(values.user_id.trim(), values.role)) form.resetFields()
              }}
              className="organization-inline-form"
            >
              <Form.Item
                name="user_id"
                rules={[{ required: true, message: '请选择用户或输入完整用户 ID' }]}
              >
                <OrganizationMemberPicker
                  members={members}
                  canSearchUsers={canSearchUsers}
                  disabled={pending}
                />
              </Form.Item>
              <Form.Item name="role" initialValue="member">
                <Select aria-label="成员角色" style={{ width: 120 }} options={roleOptions} />
              </Form.Item>
              <Button
                aria-label="添加 / 更新"
                htmlType="submit"
                type="primary"
                loading={pending}
                disabled={pending}
              >
                添加 / 更新
              </Button>
            </Form>
          )}
          <Typography.Paragraph type="secondary">
            Owner（所有者）：成员、治理与密钥轮换；Admin（管理员）：成员与治理；Member（成员）/
            Viewer（只读成员）：按已有授权读取组织信息，不能管理组织。
          </Typography.Paragraph>
          <Table
            rowKey="id"
            size="small"
            dataSource={members}
            pagination={{ pageSize: 8, hideOnSinglePage: true }}
            columns={[
              {
                title: '用户',
                render: (_, member) => (
                  <Space orientation="vertical" size={0}>
                    <Typography.Text>{member.display_name ?? member.user_id}</Typography.Text>
                    <Typography.Text type="secondary">
                      {member.email ?? '身份摘要未提供'}
                    </Typography.Text>
                    <Typography.Text code>{member.user_id}</Typography.Text>
                  </Space>
                ),
              },
              {
                title: '角色',
                render: (_, member) => (
                  <Select
                    value={member.role}
                    disabled={!canManage || pending}
                    aria-label={`更新 ${member.user_id} 角色`}
                    options={roleOptions}
                    onChange={(role: OrganizationRole) => void onMemberChange(member.user_id, role)}
                    style={{ width: 110 }}
                  />
                ),
              },
              { title: '加入时间', dataIndex: 'created_at', render: formatDate },
            ]}
          />
        </Card>
      </Col>
    </Row>
  )
}

function OrganizationMemberPicker({
  members,
  canSearchUsers,
  value,
  onChange,
  disabled,
}: {
  members: OrganizationMember[]
  canSearchUsers: boolean
  value?: string
  onChange?: (value: string | undefined) => void
  disabled?: boolean
}) {
  const [advanced, setAdvanced] = useState(false)
  if (canSearchUsers)
    return (
      <DirectoryPicker
        source={{ kind: 'user' }}
        label="组织用户"
        value={value}
        onChange={onChange}
        disabled={disabled}
      />
    )
  return (
    <Space orientation="vertical" size={4}>
      {advanced ? (
        <Input
          aria-label="用户 ID"
          placeholder="输入完整 UUID"
          value={value ?? ''}
          onChange={(event) => onChange?.(event.target.value)}
          disabled={disabled}
        />
      ) : (
        <Select
          aria-label="组织用户"
          placeholder="搜索已有组织成员"
          showSearch
          optionFilterProp="label"
          value={value}
          onChange={onChange}
          disabled={disabled}
          style={{ width: 260 }}
          options={members.map((member) => ({
            value: member.user_id,
            label: `${member.display_name ?? member.user_id} (${member.email ?? member.user_id})`,
          }))}
        />
      )}
      <Button type="link" size="small" onClick={() => setAdvanced(!advanced)} disabled={disabled}>
        {advanced ? '返回成员搜索' : '按 ID 输入'}
      </Button>
      <Typography.Text type="secondary">
        仅搜索已有组织成员；添加其他已知账号请使用完整用户 ID。
      </Typography.Text>
    </Space>
  )
}

function ServiceAccountsTab({
  form,
  accounts,
  canManage,
  issuedToken,
  onClearToken,
  onCreate,
  onRotate,
  onRevoke,
  pending,
  error,
}: {
  form: FormInstance<ServiceAccountFormValues>
  accounts: ServiceAccount[]
  canManage: boolean
  issuedToken: string | null
  onClearToken: () => void
  onCreate: (input: ServiceAccountFormValues) => Promise<boolean>
  onRotate: (id: string) => void
  onRevoke: (id: string) => void
  pending: boolean
  error: unknown
}) {
  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      {issuedToken && (
        <Alert
          showIcon
          type="warning"
          title="令牌只显示一次"
          description={
            <Space orientation="vertical">
              <Typography.Text code copyable>
                {issuedToken}
              </Typography.Text>
              <Button size="small" onClick={onClearToken}>
                我已安全保存
              </Button>
            </Space>
          }
        />
      )}
      {canManage && (
        <Card title="签发最小权限 Service Account">
          {error ? (
            <Alert
              type="error"
              showIcon
              title="Service Account 创建失败"
              description={apiErrorWithTrace(error)}
            />
          ) : null}
          <Form
            form={form}
            layout="vertical"
            disabled={pending}
            onFinish={async (values) => {
              if (pending) return
              await onCreate(values)
            }}
          >
            <Row gutter={12}>
              <Col xs={24} md={8}>
                <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                  <Input placeholder="回归机器人" />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item name="account_key" label="稳定标识" rules={[{ required: true }]}>
                  <Input placeholder="regression-bot" />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item name="scopes" label="Scope" rules={[{ required: true }]}>
                  <Select
                    mode="multiple"
                    options={serviceAccountScopes.map((scope) => ({ value: scope }))}
                  />
                </Form.Item>
              </Col>
            </Row>
            <Button type="primary" htmlType="submit" loading={pending}>
              签发令牌
            </Button>
          </Form>
        </Card>
      )}
      <Card title="已签发账号">
        <Table
          rowKey="id"
          size="small"
          dataSource={accounts}
          pagination={{ pageSize: 8, hideOnSinglePage: true }}
          columns={[
            { title: '名称', dataIndex: 'name' },
            { title: '标识', dataIndex: 'account_key' },
            { title: 'Token Prefix', dataIndex: 'token_prefix' },
            {
              title: 'Scope',
              render: (_, account) => account.scopes.map((scope) => <Tag key={scope}>{scope}</Tag>),
            },
            {
              title: '状态',
              render: (_, account) =>
                account.enabled ? <Tag color="green">启用</Tag> : <Tag color="red">已撤销</Tag>,
            },
            {
              title: '操作',
              render: (_, account) =>
                canManage ? (
                  <Space>
                    <Button size="small" onClick={() => onRotate(account.id)} loading={pending}>
                      轮换
                    </Button>
                    <Button
                      size="small"
                      danger
                      disabled={!account.enabled}
                      onClick={() => onRevoke(account.id)}
                      loading={pending}
                    >
                      撤销
                    </Button>
                  </Space>
                ) : null,
            },
          ]}
        />
      </Card>
    </Space>
  )
}

function GovernanceTab({
  organization,
  runner,
  canManage,
  pending,
  onSave,
}: {
  organization: OrganizationGovernance
  runner: ReturnType<typeof useOrganizationWorkspace>['runner']
  canManage: boolean
  pending: boolean
  onSave: (input: GovernanceFormValues) => void
}) {
  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <OrganizationQueryBoundary label="Runner 治理" query={runner}>
        {(data) => (
          <>
            <RunnerGovernanceStats runner={data} />
            <RunnerPoolsTable pools={data.pools} />
          </>
        )}
      </OrganizationQueryBoundary>
      {!canManage && (
        <Typography.Paragraph type="secondary">
          保存策略需要管理权限与完整的 Runner 治理读取结果。
        </Typography.Paragraph>
      )}
      <GovernancePolicyForm
        organization={organization}
        canManage={canManage}
        pending={pending}
        onSave={onSave}
      />
    </Space>
  )
}

function RunnerGovernanceStats({ runner }: { runner?: RunnerGovernanceData }) {
  const items = [
    ['Runner Pool', runner?.pool_count ?? '未提供'],
    ['Runner', runner?.runner_count ?? '未提供'],
    ['当前并发', runner?.current_load ?? '未提供'],
    ['Runner 容量', runner?.capacity ?? '未提供'],
  ] as const
  return (
    <Row gutter={16}>
      {items.map(([title, value]) => (
        <Col xs={12} md={6} key={title}>
          <Card>
            <Statistic title={title} value={value} />
          </Card>
        </Col>
      ))}
    </Row>
  )
}

function GovernancePolicyForm({
  organization,
  canManage,
  pending,
  onSave,
}: {
  organization: OrganizationGovernance
  canManage: boolean
  pending: boolean
  onSave: (input: GovernanceFormValues) => void
}) {
  const [form] = Form.useForm<GovernanceFormValues>()
  const initialValues = useMemo(() => toGovernanceFormValues(organization), [organization])
  return (
    <Card title="配额与 Runner Pool 治理">
      <Form
        key={organization.organization_id}
        form={form}
        layout="vertical"
        initialValues={initialValues}
        onFinish={onSave}
        disabled={!canManage}
      >
        <Form.Item
          name="audit_retention_days"
          label="审计保留天数"
          rules={[{ required: true, min: 1, max: 3650 }]}
        >
          <InputNumber min={1} max={3650} addonAfter="天" />
        </Form.Item>
        <QuotaPolicyFields />
        <RunnerPolicyFields />
        {canManage && (
          <Button type="primary" htmlType="submit" loading={pending}>
            保存治理策略
          </Button>
        )}
      </Form>
    </Card>
  )
}

function QuotaPolicyFields() {
  return (
    <Row gutter={12}>
      {quotaDimensions.map((dimension) => (
        <Col xs={24} md={12} key={dimension.key}>
          <Card
            size="small"
            title={`${dimension.label}${dimension.unit ? ` · ${dimension.unit}` : ''}`}
          >
            <Space>
              <Form.Item name={['quota_policies', dimension.key, 'mode']} noStyle>
                <Select style={{ width: 120 }} options={quotaModes} />
              </Form.Item>
              <Form.Item name={['quota_policies', dimension.key, 'limit']} noStyle>
                <InputNumber min={1} placeholder="上限" />
              </Form.Item>
              <Form.Item name={['quota_policies', dimension.key, 'warn_at']} noStyle>
                <InputNumber min={1} placeholder="预警" />
              </Form.Item>
            </Space>
          </Card>
        </Col>
      ))}
    </Row>
  )
}

function RunnerPolicyFields() {
  return (
    <Row gutter={12}>
      <Col xs={24} md={8}>
        <Form.Item name={['runner_policy', 'allowed_runner_types']} label="允许 Runner 类型">
          <Select
            mode="multiple"
            options={['general', 'data', 'protocol', 'performance', 'environment', 'plugin'].map(
              (value) => ({ value }),
            )}
          />
        </Form.Item>
      </Col>
      <Col xs={24} md={8}>
        <Form.Item name={['runner_policy', 'allowed_runtimes']} label="允许 Runtime">
          <Select mode="multiple" options={['docker', 'kubernetes'].map((value) => ({ value }))} />
        </Form.Item>
      </Col>
      <Col xs={24} md={8}>
        <Form.Item name={['runner_policy', 'max_pools']} label="最大 Pool 数">
          <InputNumber min={1} max={500} />
        </Form.Item>
      </Col>
      <Col xs={24} md={8}>
        <Form.Item name={['runner_policy', 'registration_requires_approval']} label="注册策略">
          <Select
            options={[
              { value: false, label: 'Runner 注册自动通过' },
              { value: true, label: 'Runner 注册需要审批' },
            ]}
          />
        </Form.Item>
      </Col>
    </Row>
  )
}

function RunnerPoolsTable({ pools }: { pools: RunnerGovernanceData['pools'] }) {
  return (
    <Card title="组织 Runner Pool">
      <Table
        rowKey="id"
        size="small"
        dataSource={pools}
        pagination={false}
        columns={[
          { title: 'Pool', dataIndex: 'name' },
          { title: '类型', dataIndex: 'runner_type' },
          { title: 'Runtime', dataIndex: 'runtime' },
          { title: 'Runner 数', dataIndex: 'runner_count' },
          { title: '负载', render: (_, pool) => `${pool.current_load} / ${pool.max_concurrency}` },
          {
            title: '状态',
            render: (_, pool) => (pool.enabled ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
          },
        ]}
      />
    </Card>
  )
}

function KeyRotationCard({
  security,
  canRotate,
  onPrepare,
  onApply,
  onRollback,
  pending,
}: {
  security: SecurityView
  canRotate: boolean
  onPrepare: (input: KeyRotationFormValues) => void
  onApply: (id: string) => void
  onRollback: (id: string) => void
  pending: boolean
}) {
  const [form] = Form.useForm<KeyRotationFormValues>()
  const capabilityAvailable =
    security.ciphertext_reencryption_available === true &&
    security.capability_name === 'Organization Data Encryption Key Rotation' &&
    security.ga_blocker === null &&
    security.capability_mode === 'reencrypt_verify_activate_rollback'
  return (
    <Card
      title={
        <Space>
          <KeyOutlined />
          组织密钥轮换
        </Space>
      }
    >
      <Descriptions column={1} size="small">
        <Descriptions.Item label="当前版本">v{security.active_key_version}</Descriptions.Item>
        <Descriptions.Item label="能力标识">{security.capability_name}</Descriptions.Item>
        <Descriptions.Item label="密钥材料">外部密钥提供方（只保存引用与指纹）</Descriptions.Item>
        <Descriptions.Item label="能力模式">{security.capability_mode}</Descriptions.Item>
      </Descriptions>
      <Alert
        type={capabilityAvailable ? 'info' : 'warning'}
        showIcon
        className="page-alert"
        title={capabilityAvailable ? '密钥轮换能力已确认' : '密钥轮换能力不可用'}
        description="Apply 在同一事务内锁定组织密钥策略，逐项重加密并解密校验后才激活；Rollback 使用前一密钥反向重加密并记录审计证据。"
      />
      {canRotate && capabilityAvailable && (
        <Form form={form} layout="vertical" onFinish={onPrepare}>
          <Form.Item
            name="key_reference"
            label="新密钥引用"
            initialValue="external:data-encryption-key"
          >
            <Input placeholder="vault:flowtest/data-key-v2" />
          </Form.Item>
          <Form.Item
            name="key_fingerprint"
            label="新密钥指纹（SHA-256）"
            rules={[{ required: true, len: 64, pattern: /^[0-9a-fA-F]+$/ }]}
          >
            <Input placeholder="64 位十六进制指纹" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={pending}>
            创建轮换版本
          </Button>
        </Form>
      )}
      <KeyVersionTable
        versions={security.key_versions}
        canRotate={canRotate && capabilityAvailable && !pending}
        onApply={onApply}
        onRollback={onRollback}
      />
    </Card>
  )
}

type SecurityView = {
  active_key_version: number
  capability_name: 'Organization Data Encryption Key Rotation'
  capability_mode: 'reencrypt_verify_activate_rollback'
  ciphertext_reencryption_available: true
  ga_blocker: null
  key_versions: SecurityKeyVersion[]
}

function KeyVersionTable({
  versions,
  canRotate,
  onApply,
  onRollback,
}: {
  versions: SecurityView['key_versions']
  canRotate: boolean
  onApply: (id: string) => void
  onRollback: (id: string) => void
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      dataSource={versions}
      pagination={false}
      columns={[
        { title: '版本', render: (_, item) => `v${item.version}` },
        { title: '引用', dataIndex: 'key_reference', ellipsis: true },
        { title: '指纹', dataIndex: 'key_fingerprint', ellipsis: true },
        {
          title: '迁移状态',
          dataIndex: 'migration_status',
          render: (value: string) => (
            <Space>
              <Tag>{value}</Tag>
              <Typography.Text type="secondary">仅在校验后标记 migrated</Typography.Text>
            </Space>
          ),
        },
        { title: '状态', dataIndex: 'status' },
        {
          title: '操作',
          render: (_, item) => rotationAction(item, canRotate, onApply, onRollback),
        },
      ]}
    />
  )
}

function SupportBundleCard({ supportBundle }: { supportBundle?: SupportBundleView }) {
  return (
    <Card
      title={
        <Space>
          <SafetyCertificateOutlined />
          支持包脱敏
        </Space>
      }
    >
      <Typography.Paragraph type="secondary">
        Support Bundle 只生成经过字段级脱敏的诊断清单，不包含密码、密钥、Token、密文或私钥。
      </Typography.Paragraph>
      <Descriptions column={1} size="small">
        <Descriptions.Item label="Schema">{supportBundle?.schema_version ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="分类">
          {supportBundle?.data_classification ?? '-'}
        </Descriptions.Item>
        <Descriptions.Item label="排除字段">
          {supportBundle?.excluded_fields.join('、') ?? '-'}
        </Descriptions.Item>
      </Descriptions>
    </Card>
  )
}

type SupportBundleView = {
  schema_version: string
  data_classification: string
  included_sections: string[]
  redacted_fields: string[]
  excluded_fields: string[]
}

function CreateOrganizationDialog({
  open,
  submitting,
  onClose,
  onCreate,
}: {
  open: boolean
  submitting: boolean
  onClose: () => void
  onCreate: (values: { name: string; slug?: string; description?: string }) => void
}) {
  const [form] = Form.useForm()
  return (
    <Modal
      open={open}
      title="新建组织"
      okText="创建"
      cancelText="取消"
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => void form.submit()}
    >
      <Form form={form} layout="vertical" onFinish={onCreate}>
        <Form.Item name="name" label="名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="slug" label="Slug">
          <Input />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={3} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

const roleOptions = [
  { value: 'owner' as const, label: '所有者 Owner' },
  { value: 'admin' as const, label: '管理员 Admin' },
  { value: 'member' as const, label: '成员 Member' },
  { value: 'viewer' as const, label: '只读成员 Viewer' },
]

function toGovernanceFormValues(value: OrganizationGovernance): GovernanceFormValues {
  return {
    audit_retention_days: value.audit_retention_days,
    quota_policies: value.quota_policies,
    runner_policy: value.runner_policy,
  }
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
