import { DeleteOutlined, TeamOutlined, UserAddOutlined } from '@ant-design/icons'
import {
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type QueryKey,
} from '@tanstack/react-query'
import { App, Button, Card, Form, Input, Popconfirm, Select, Space, Table, Tabs, Tag } from 'antd'
import { useLayoutEffect, useRef, useState } from 'react'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import DirectoryPicker from './DirectoryPicker'

import { useAuthStore } from '../auth/auth-store'
import {
  addTeamMember,
  createTeam as createTeamRequest,
  createUser,
  listProjectMembers,
  listProjectTeamGrants,
  listTeamMembers,
  removeProjectMember,
  removeProjectTeamGrant,
  removeTeamMember,
  upsertProjectMember,
  upsertProjectTeamGrant,
} from './access-service'
import {
  apiErrorMessage,
  SessionBoundaryError,
  type ProjectMember,
  type ProjectTeamGrant,
} from '../../lib/api'

type AccessManagementPanelProps = {
  projectId: string
  canManage: boolean
}

type AccessCommand = {
  projectId: string
  operation: () => Promise<unknown>
  teamId?: string
  directory?: 'user' | 'team'
}

type AccessCommandTargets = Pick<AccessCommand, 'teamId' | 'directory'>

export default function AccessManagementPanel({
  projectId,
  canManage,
}: AccessManagementPanelProps) {
  const state = useAccessManagement(projectId, canManage)
  return (
    <Card title="成员与团队" className="management-card">
      <Tabs
        activeKey={state.activeTab}
        onChange={state.setActiveTab}
        items={[
          {
            key: 'members',
            label: '项目成员',
            children: <ProjectMembers state={state} canManage={canManage} />,
          },
          {
            key: 'grants',
            label: '团队授权',
            children: <TeamGrants state={state} canManage={canManage} />,
          },
          ...(state.isAdministrator
            ? [
                {
                  key: 'organization',
                  label: '用户与团队',
                  children: <OrganizationManagement state={state} />,
                },
              ]
            : []),
        ]}
      />
    </Card>
  )
}

function useAccessManagement(projectId: string, canManage: boolean) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const isAdministrator = useAuthStore((value) => Boolean(value.user?.is_system_admin))
  const projectPending = useIsMutating({ mutationKey: ['project-access', projectId] }) > 0
  const commandPending = useRef(false)
  const commandAccess = useRef({ canManage, isAdministrator, projectPending })
  const active = useRef(true)
  useLayoutEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  useLayoutEffect(() => {
    commandAccess.current = { canManage, isAdministrator, projectPending }
  }, [canManage, isAdministrator, projectPending])
  const [activeTab, setActiveTab] = useState('members')
  const [teamId, setTeamId] = useState<string | null>(null)
  const [teamLabel, setTeamLabel] = useState<string | undefined>()
  const members = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => listProjectMembers(projectId),
  })
  const grants = useQuery({
    queryKey: ['project-team-grants', projectId],
    queryFn: () => listProjectTeamGrants(projectId),
  })
  const selectedTeamId = teamId
  const teamMembers = useQuery({
    queryKey: ['team-members', selectedTeamId],
    queryFn: () => listTeamMembers(required(selectedTeamId)),
    enabled: Boolean(selectedTeamId) && isAdministrator && activeTab === 'organization',
  })
  const mutation = useMutation({
    mutationKey: ['project-access', projectId],
    mutationFn: async (command: AccessCommand) => command.operation(),
    onSuccess: async (_, command) => {
      const projectId = command.projectId
      const refreshes = await Promise.allSettled([
        queryClient.invalidateQueries({ queryKey: ['project-members', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['project-team-grants', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['team-members'] }),
        queryClient.invalidateQueries({ queryKey: ['access-directory'] }),
        queryClient.invalidateQueries({ queryKey: ['project-audit', projectId] }),
        ...refreshAccessReads(queryClient, ['project-permissions', projectId]),
        ...refreshAccessReads(queryClient, ['project-permission', projectId]),
        ...refreshAccessReads(queryClient, ['project', projectId]),
        ...refreshAccessReads(queryClient, ['projects'], 'active'),
      ])
      const failed = refreshes.find((result) => result.status === 'rejected')
      if (failed) throw failed.reason
      if (!active.current) return
      void message.success('成员与团队配置已更新')
    },
    onError: async (error, command) => {
      if (error instanceof SessionBoundaryError) await invalidateAccessCommand(queryClient, command)
      if (active.current) void message.error(apiErrorMessage(error))
    },
    onSettled: () => {
      commandPending.current = false
    },
  })

  function run(operation: AccessCommand['operation'], targets: AccessCommandTargets = {}): void {
    const access = commandAccess.current
    if (!active.current || commandPending.current || access.projectPending) return
    const requiresAdministrator = Boolean(targets.teamId || targets.directory)
    if (requiresAdministrator ? !access.isAdministrator : !access.canManage) return
    commandPending.current = true
    mutation.mutate({ projectId, operation, ...targets })
  }

  function createAndSelectTeam(values: { name: string; description: string }) {
    run(
      async () => {
        const created = await createTeamRequest(values)
        if (active.current) {
          setTeamId(created.id)
          setTeamLabel(created.name)
        }
        return created
      },
      { directory: 'team' },
    )
  }
  return {
    projectId,
    isAdministrator,
    activeTab,
    setActiveTab,
    membersQuery: members,
    grantsQuery: grants,
    teamMembersQuery: teamMembers,
    teamLabel,
    members: arrayItems(members.data),
    membersLoading: members.isLoading,
    grants: arrayItems(grants.data),
    grantsLoading: grants.isLoading,
    selectedTeamId,
    setTeamId: (id: string | undefined) => {
      setTeamId(id ?? null)
      setTeamLabel(undefined)
    },
    teamMembers: arrayItems(teamMembers.data),
    teamMembersLoading: teamMembers.isLoading,
    pending: mutation.isPending || projectPending,
    run,
    createAndSelectTeam,
  }
}

async function invalidateAccessCommand(client: QueryClient, command: AccessCommand): Promise<void> {
  const { projectId, teamId, directory } = command
  const keys: QueryKey[] = [
    ['project-members', projectId],
    ['project-team-grants', projectId],
    ['project-audit', projectId],
    ['project-permissions', projectId],
    ['project-permission', projectId],
    ['project', projectId],
    ['projects'],
    ['access-directory', { kind: 'project-user', projectId }],
  ]
  if (teamId) keys.push(['team-members', teamId])
  if (directory) keys.push(['access-directory', { kind: directory }])
  if (directory === 'user') keys.push(['access-directory', { kind: 'project-user' }])
  await Promise.all(keys.map((queryKey) => client.cancelQueries({ queryKey })))
  await Promise.all(
    keys.map((queryKey) => client.invalidateQueries({ queryKey, refetchType: 'none' })),
  )
}

function refreshAccessReads(
  client: QueryClient,
  queryKey: QueryKey,
  type: 'all' | 'active' = 'all',
): Promise<void>[] {
  const queries = client.getQueryCache().findAll({ queryKey, type })
  return [
    client.invalidateQueries({ queryKey, refetchType: 'none' }),
    ...queries.map((query) =>
      client.refetchQueries(
        { queryKey: query.queryKey, exact: true, type },
        { throwOnError: true },
      ),
    ),
  ]
}

type AccessState = ReturnType<typeof useAccessManagement>

function ProjectMembers({ state, canManage }: { state: AccessState; canManage: boolean }) {
  const [form] = Form.useForm<{ user_id: string; role: ProjectMember['role'] }>()
  return (
    <Space orientation="vertical" className="full-width">
      {(canManage || state.pending) && (
        <Form
          form={form}
          disabled={!canManage || state.pending}
          layout="inline"
          initialValues={{ role: 'viewer' }}
          onFinish={(values) =>
            state.run(() => upsertProjectMember(state.projectId, values.user_id, values.role))
          }
        >
          <Form.Item name="user_id" rules={identityRules('请选择或输入用户')}>
            <DirectoryPicker
              source={{ kind: 'project-user', projectId: state.projectId }}
              label="项目用户"
              disabled={!canManage || state.pending}
            />
          </Form.Item>
          <Form.Item name="role">
            <Select
              aria-label="项目成员角色"
              className="role-select"
              options={['owner', 'editor', 'viewer'].map((role) => ({ value: role, label: role }))}
            />
          </Form.Item>
          <Button
            htmlType="submit"
            type="primary"
            icon={<UserAddOutlined />}
            loading={state.pending}
            disabled={!canManage || state.pending || !state.membersQuery.isSuccess}
          >
            添加成员
          </Button>
        </Form>
      )}
      <QueryFailureNotice queries={[state.membersQuery]} />
      <Table
        rowKey="id"
        size="small"
        locale={{ emptyText: state.membersQuery.isError ? '成员读取失败，请重试' : '无项目成员' }}
        loading={state.membersLoading}
        pagination={false}
        dataSource={state.members}
        columns={[
          { title: '用户', render: (_, member) => <MemberIdentity member={member} /> },
          { title: '角色', dataIndex: 'role', width: 120, render: (role) => <Tag>{role}</Tag> },
          {
            title: '操作',
            width: 80,
            render: (_, member) =>
              canManage ? (
                <Popconfirm
                  title="确认移除该成员？"
                  onConfirm={() =>
                    state.run(() => removeProjectMember(state.projectId, member.user_id))
                  }
                >
                  <Button
                    type="text"
                    danger
                    disabled={state.pending || !state.membersQuery.isSuccess}
                    icon={<DeleteOutlined />}
                    aria-label="移除项目成员"
                  />
                </Popconfirm>
              ) : null,
          },
        ]}
      />
    </Space>
  )
}

function TeamGrants({ state, canManage }: { state: AccessState; canManage: boolean }) {
  const [form] = Form.useForm<{ team_id: string; role: ProjectTeamGrant['role'] }>()
  return (
    <Space orientation="vertical" className="full-width">
      {(canManage || state.pending) && (
        <Form
          form={form}
          disabled={!canManage || state.pending}
          layout="inline"
          initialValues={{ role: 'viewer' }}
          onFinish={(values) =>
            state.run(() => upsertProjectTeamGrant(state.projectId, values.team_id, values.role))
          }
        >
          <Form.Item name="team_id" rules={identityRules('请选择团队')}>
            <DirectoryPicker
              source={{ kind: 'team' }}
              label="授权团队"
              disabled={!canManage || state.pending}
            />
          </Form.Item>
          <Form.Item name="role">
            <Select
              aria-label="团队授权角色"
              className="role-select"
              options={['editor', 'viewer'].map((role) => ({ value: role, label: role }))}
            />
          </Form.Item>
          <Button
            htmlType="submit"
            type="primary"
            icon={<TeamOutlined />}
            loading={state.pending}
            disabled={!canManage || state.pending || !state.grantsQuery.isSuccess}
          >
            授权团队
          </Button>
        </Form>
      )}
      <QueryFailureNotice queries={[state.grantsQuery]} />
      <Table
        rowKey="id"
        size="small"
        locale={{
          emptyText: state.grantsQuery.isError ? '团队授权读取失败，请重试' : '无团队授权',
        }}
        loading={state.grantsLoading}
        pagination={false}
        dataSource={state.grants}
        columns={[
          {
            title: '团队',
            dataIndex: 'team_id',
            render: (_, grant) => (
              <Space orientation="vertical" size={0}>
                <span>{grant.team_name || '名称未提供'}</span>
                <span>{grant.team_id}</span>
              </Space>
            ),
          },
          { title: '角色', dataIndex: 'role', width: 120, render: (role) => <Tag>{role}</Tag> },
          {
            title: '操作',
            width: 80,
            render: (_, grant) =>
              canManage ? (
                <Popconfirm
                  title="确认移除团队授权？"
                  onConfirm={() =>
                    state.run(() => removeProjectTeamGrant(state.projectId, grant.team_id))
                  }
                >
                  <Button
                    type="text"
                    danger
                    disabled={state.pending || !state.grantsQuery.isSuccess}
                    icon={<DeleteOutlined />}
                    aria-label="移除团队授权"
                  />
                </Popconfirm>
              ) : null,
          },
        ]}
      />
    </Space>
  )
}

function OrganizationManagement({ state }: { state: AccessState }) {
  return (
    <Space orientation="vertical" className="full-width" size="large">
      <CreateOrganizationEntities state={state} />
      <TeamMembership state={state} />
    </Space>
  )
}

function CreateOrganizationEntities({ state }: { state: AccessState }) {
  const [userForm] = Form.useForm<{
    email: string
    display_name: string
    password: string
  }>()
  const [teamForm] = Form.useForm<{ name: string; description: string }>()
  return (
    <Space wrap align="start">
      <Form
        form={userForm}
        disabled={state.pending}
        layout="inline"
        onFinish={(values) =>
          state.run(() => createUser({ ...values, is_system_admin: false }), { directory: 'user' })
        }
      >
        <Form.Item name="email" rules={[{ required: true, type: 'email' }]}>
          <Input placeholder="用户邮箱" />
        </Form.Item>
        <Form.Item name="display_name" rules={[{ required: true }]}>
          <Input placeholder="显示名" />
        </Form.Item>
        <Form.Item name="password" rules={[{ required: true, min: 8 }]}>
          <Input.Password placeholder="初始密码（至少 8 位）" />
        </Form.Item>
        <Button htmlType="submit" loading={state.pending}>
          创建用户
        </Button>
      </Form>
      <Form
        form={teamForm}
        disabled={state.pending}
        layout="inline"
        onFinish={state.createAndSelectTeam}
      >
        <Form.Item name="name" rules={[{ required: true }]}>
          <Input placeholder="团队名称" />
        </Form.Item>
        <Form.Item name="description">
          <Input placeholder="团队说明" />
        </Form.Item>
        <Button htmlType="submit" loading={state.pending}>
          创建团队
        </Button>
      </Form>
    </Space>
  )
}

function TeamMembership({ state }: { state: AccessState }) {
  const [form] = Form.useForm<{ user_id: string }>()
  return (
    <Space orientation="vertical" className="full-width">
      <Space wrap>
        <DirectoryPicker
          source={{ kind: 'team' }}
          label="管理团队"
          value={state.selectedTeamId}
          selectedLabel={state.teamLabel}
          onChange={state.setTeamId}
          disabled={state.pending}
        />
        <Form
          form={form}
          disabled={state.pending}
          layout="inline"
          onFinish={(values) =>
            state.run(() => addTeamMember(required(state.selectedTeamId), values.user_id), {
              teamId: required(state.selectedTeamId),
            })
          }
        >
          <Form.Item name="user_id" rules={identityRules('请选择团队用户')}>
            <DirectoryPicker source={{ kind: 'user' }} label="团队用户" disabled={state.pending} />
          </Form.Item>
          <Button
            htmlType="submit"
            disabled={state.pending || !state.selectedTeamId || !state.teamMembersQuery.isSuccess}
            loading={state.pending}
          >
            添加到团队
          </Button>
        </Form>
      </Space>
      <QueryFailureNotice queries={[state.teamMembersQuery]} />
      <Table
        rowKey="id"
        size="small"
        locale={{ emptyText: teamEmptyText(state.selectedTeamId, state.teamMembersQuery.isError) }}
        loading={state.teamMembersLoading}
        pagination={false}
        dataSource={state.teamMembers}
        columns={[
          {
            title: '成员',
            dataIndex: 'user_id',
            render: (_, member) => <MemberIdentity member={member} />,
          },
          {
            title: '操作',
            width: 80,
            render: (_, member) => (
              <Popconfirm
                title="确认移除团队成员？"
                onConfirm={() =>
                  state.run(() => removeTeamMember(member.team_id, member.user_id), {
                    teamId: member.team_id,
                  })
                }
              >
                <Button
                  type="text"
                  danger
                  disabled={state.pending || !state.teamMembersQuery.isSuccess}
                  icon={<DeleteOutlined />}
                  aria-label="移除团队成员"
                />
              </Popconfirm>
            ),
          },
        ]}
      />
    </Space>
  )
}

function required(value: string | null): string {
  if (!value) throw new Error('缺少团队标识')
  return value
}

function arrayItems<T>(items?: T[]): T[] {
  return items ?? []
}

function MemberIdentity({
  member,
}: {
  member: { user_id: string; display_name?: string | null; email?: string | null }
}) {
  return (
    <Space orientation="vertical" size={0}>
      <span>{member.display_name || '名称未提供'}</span>
      <span>{member.email || '邮箱未提供'}</span>
      <span>{member.user_id}</span>
    </Space>
  )
}

function identityRules(message: string) {
  return [
    { required: true, message },
    {
      pattern: /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
      message: '请输入完整有效的 UUID',
    },
  ]
}

function teamEmptyText(teamId: string | null, failed: boolean): string {
  if (!teamId) return '请先选择要管理的团队'
  return failed ? '团队成员读取失败，请重试' : '无团队成员'
}
