import { DeleteOutlined, TeamOutlined, UserAddOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App, Button, Card, Form, Input, Popconfirm, Select, Space, Table, Tabs, Tag } from 'antd'
import { useState } from 'react'

import { useAuthStore } from '../auth/auth-store'
import {
  addTeamMember,
  createTeam,
  createUser,
  listProjectMembers,
  listProjectTeamGrants,
  listTeamMembers,
  listTeams,
  listUsers,
  removeProjectMember,
  removeProjectTeamGrant,
  removeTeamMember,
  upsertProjectMember,
  upsertProjectTeamGrant,
} from './access-service'
import { apiErrorMessage, type ProjectMember, type ProjectTeamGrant } from '../../lib/api'

type AccessManagementPanelProps = {
  projectId: string
  canManage: boolean
}

export default function AccessManagementPanel({
  projectId,
  canManage,
}: AccessManagementPanelProps) {
  const state = useAccessManagement(projectId)
  return (
    <Card title="成员与团队" className="management-card">
      <Tabs
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

function useAccessManagement(projectId: string) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const isAdministrator = useAuthStore((value) => Boolean(value.user?.is_system_admin))
  const [teamId, setTeamId] = useState<string | null>(null)
  const users = useQuery({
    queryKey: ['users'],
    queryFn: listUsers,
    enabled: isAdministrator,
  })
  const members = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => listProjectMembers(projectId),
  })
  const teams = useQuery({ queryKey: ['teams'], queryFn: listTeams })
  const grants = useQuery({
    queryKey: ['project-team-grants', projectId],
    queryFn: () => listProjectTeamGrants(projectId),
  })
  const selectedTeamId = selectedTeam(teamId, teams.data?.items)
  const teamMembers = useQuery({
    queryKey: ['team-members', selectedTeamId],
    queryFn: () => listTeamMembers(required(selectedTeamId)),
    enabled: Boolean(selectedTeamId) && isAdministrator,
  })
  const mutation = useMutation({
    mutationFn: async (operation: () => Promise<unknown>) => operation(),
    onSuccess: async () => {
      await queryClient.invalidateQueries()
      void message.success('成员与团队配置已更新')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  return {
    projectId,
    isAdministrator,
    users: pageItems(users.data),
    members: arrayItems(members.data),
    membersLoading: members.isLoading,
    teams: pageItems(teams.data),
    grants: arrayItems(grants.data),
    grantsLoading: grants.isLoading,
    selectedTeamId,
    setTeamId,
    teamMembers: arrayItems(teamMembers.data),
    teamMembersLoading: teamMembers.isLoading,
    pending: mutation.isPending,
    run: mutation.mutate,
  }
}

type AccessState = ReturnType<typeof useAccessManagement>

function ProjectMembers({ state, canManage }: { state: AccessState; canManage: boolean }) {
  const [form] = Form.useForm<{ user_id: string; role: ProjectMember['role'] }>()
  return (
    <Space orientation="vertical" className="full-width">
      {canManage && (
        <Form
          form={form}
          layout="inline"
          initialValues={{ role: 'viewer' }}
          onFinish={(values) =>
            state.run(() => upsertProjectMember(state.projectId, values.user_id, values.role))
          }
        >
          <Form.Item name="user_id" rules={[{ required: true, message: '请选择或输入用户' }]}>
            {state.users.length ? (
              <Select
                showSearch
                placeholder="用户"
                className="management-select"
                options={state.users.map((user) => ({
                  value: user.id,
                  label: `${user.display_name} (${user.email})`,
                }))}
              />
            ) : (
              <Input placeholder="用户 UUID" />
            )}
          </Form.Item>
          <Form.Item name="role">
            <Select
              className="role-select"
              options={['owner', 'editor', 'viewer'].map((role) => ({ value: role, label: role }))}
            />
          </Form.Item>
          <Button
            htmlType="submit"
            type="primary"
            icon={<UserAddOutlined />}
            loading={state.pending}
          >
            添加成员
          </Button>
        </Form>
      )}
      <Table
        rowKey="id"
        size="small"
        loading={state.membersLoading}
        pagination={false}
        dataSource={state.members}
        columns={[
          { title: '用户', dataIndex: 'user_id' },
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
                  <Button type="text" danger icon={<DeleteOutlined />} aria-label="移除项目成员" />
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
      {canManage && (
        <Form
          form={form}
          layout="inline"
          initialValues={{ role: 'viewer' }}
          onFinish={(values) =>
            state.run(() => upsertProjectTeamGrant(state.projectId, values.team_id, values.role))
          }
        >
          <Form.Item name="team_id" rules={[{ required: true, message: '请选择团队' }]}>
            <Select
              placeholder="团队"
              className="management-select"
              options={state.teams.map((team) => ({ value: team.id, label: team.name }))}
            />
          </Form.Item>
          <Form.Item name="role">
            <Select
              className="role-select"
              options={['editor', 'viewer'].map((role) => ({ value: role, label: role }))}
            />
          </Form.Item>
          <Button htmlType="submit" type="primary" icon={<TeamOutlined />} loading={state.pending}>
            授权团队
          </Button>
        </Form>
      )}
      <Table
        rowKey="id"
        size="small"
        loading={state.grantsLoading}
        pagination={false}
        dataSource={state.grants}
        columns={[
          {
            title: '团队',
            dataIndex: 'team_id',
            render: (teamId) => state.teams.find((team) => team.id === teamId)?.name ?? teamId,
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
                  <Button type="text" danger icon={<DeleteOutlined />} aria-label="移除团队授权" />
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
        layout="inline"
        onFinish={(values) => state.run(() => createUser({ ...values, is_system_admin: false }))}
      >
        <Form.Item name="email" rules={[{ required: true, type: 'email' }]}>
          <Input placeholder="用户邮箱" />
        </Form.Item>
        <Form.Item name="display_name" rules={[{ required: true }]}>
          <Input placeholder="显示名" />
        </Form.Item>
        <Form.Item name="password" rules={[{ required: true, min: 12 }]}>
          <Input.Password placeholder="初始密码（至少 12 位）" />
        </Form.Item>
        <Button htmlType="submit" loading={state.pending}>
          创建用户
        </Button>
      </Form>
      <Form
        form={teamForm}
        layout="inline"
        onFinish={(values) => state.run(() => createTeam(values))}
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
        <Select
          aria-label="管理团队"
          className="management-select"
          value={state.selectedTeamId}
          onChange={state.setTeamId}
          options={state.teams.map((team) => ({ value: team.id, label: team.name }))}
        />
        <Form
          form={form}
          layout="inline"
          onFinish={(values) =>
            state.run(() => addTeamMember(required(state.selectedTeamId), values.user_id))
          }
        >
          <Form.Item name="user_id" rules={[{ required: true }]}>
            <Select
              placeholder="添加用户"
              className="management-select"
              options={state.users.map((user) => ({ value: user.id, label: user.email }))}
            />
          </Form.Item>
          <Button htmlType="submit" disabled={!state.selectedTeamId} loading={state.pending}>
            添加到团队
          </Button>
        </Form>
      </Space>
      <Table
        rowKey="id"
        size="small"
        loading={state.teamMembersLoading}
        pagination={false}
        dataSource={state.teamMembers}
        columns={[
          {
            title: '成员',
            dataIndex: 'user_id',
            render: (userId) => state.users.find((user) => user.id === userId)?.email ?? userId,
          },
          {
            title: '操作',
            width: 80,
            render: (_, member) => (
              <Popconfirm
                title="确认移除团队成员？"
                onConfirm={() => state.run(() => removeTeamMember(member.team_id, member.user_id))}
              >
                <Button type="text" danger icon={<DeleteOutlined />} aria-label="移除团队成员" />
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

function selectedTeam(selection: string | null, teams?: Array<{ id: string }>): string | null {
  if (selection) return selection
  return teams?.at(0)?.id ?? null
}

function pageItems<T>(page?: { items: T[] }): T[] {
  return page?.items ?? []
}

function arrayItems<T>(items?: T[]): T[] {
  return items ?? []
}
