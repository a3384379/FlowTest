import { DeleteOutlined, EditOutlined, FolderAddOutlined, KeyOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App, Button, Card, Form, Input, Popconfirm, Select, Space, Table, Tabs, Tag } from 'antd'
import { useState } from 'react'

import {
  createEnvironment,
  createFolder,
  deleteFolder,
  getProjectConfiguration,
  listEnvironments,
  listFolders,
  listSecrets,
  updateEnvironment,
  updateFolder,
  updateProjectConfiguration,
  writeSecret,
} from './asset-service'
import { apiErrorMessage, type Environment, type Folder } from '../../lib/api'

export default function AssetManagementPanel({
  projectId,
  canEdit,
}: {
  projectId: string
  canEdit: boolean
}) {
  const state = useAssetManagement(projectId)
  return (
    <Card title="测试资产配置" className="management-card">
      <Tabs
        items={[
          {
            key: 'folders',
            label: '目录',
            children: <FolderManagement state={state} canEdit={canEdit} />,
          },
          {
            key: 'configuration',
            label: '项目变量与 Header',
            children: <ConfigurationManagement state={state} canEdit={canEdit} />,
          },
          {
            key: 'environments',
            label: '环境',
            children: <EnvironmentManagement state={state} canEdit={canEdit} />,
          },
          {
            key: 'secrets',
            label: 'Secret',
            children: <SecretManagement state={state} canEdit={canEdit} />,
          },
        ]}
      />
    </Card>
  )
}

function useAssetManagement(projectId: string) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const folders = useQuery({
    queryKey: ['folders', projectId],
    queryFn: () => listFolders(projectId),
  })
  const configuration = useQuery({
    queryKey: ['project-configuration', projectId],
    queryFn: () => getProjectConfiguration(projectId),
  })
  const environments = useQuery({
    queryKey: ['environments', projectId],
    queryFn: () => listEnvironments(projectId),
  })
  const secrets = useQuery({
    queryKey: ['secrets', projectId],
    queryFn: () => listSecrets(projectId),
  })
  const mutation = useMutation({
    mutationFn: async (operation: () => Promise<unknown>) => operation(),
    onSuccess: async () => {
      await Promise.all(
        [
          ['folders', projectId],
          ['project-configuration', projectId],
          ['environments', projectId],
          ['secrets', projectId],
          ['project-audit', projectId],
        ].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      )
      void message.success('测试资产配置已保存')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  return {
    projectId,
    folders: folders.data ?? [],
    foldersLoading: folders.isLoading,
    configuration: configuration.data,
    configurationLoading: configuration.isLoading,
    environments: environments.data ?? [],
    environmentsLoading: environments.isLoading,
    secrets: secrets.data ?? [],
    secretsLoading: secrets.isLoading,
    pending: mutation.isPending,
    run: mutation.mutate,
  }
}

type AssetState = ReturnType<typeof useAssetManagement>

function FolderManagement({ state, canEdit }: { state: AssetState; canEdit: boolean }) {
  const [editing, setEditing] = useState<Folder | null>(null)
  const [form] = Form.useForm<{ name: string; parent_id: string | null }>()
  function save(values: { name: string; parent_id: string | null }) {
    const operation = editing
      ? () => updateFolder(state.projectId, editing.id, values)
      : () => createFolder(state.projectId, values)
    state.run(operation)
    setEditing(null)
    form.resetFields()
  }
  function beginEditing(folder: Folder) {
    form.setFieldsValue({ name: folder.name, parent_id: folder.parent_id })
    setEditing(folder)
  }
  function cancelEditing() {
    setEditing(null)
    form.resetFields()
  }
  return (
    <Space orientation="vertical" className="full-width">
      {canEdit && (
        <Form form={form} layout="inline" initialValues={{ parent_id: null }} onFinish={save}>
          <Form.Item name="name" rules={[{ required: true, message: '请输入目录名' }]}>
            <Input placeholder="目录名称" />
          </Form.Item>
          <Form.Item name="parent_id">
            <Select
              allowClear
              placeholder="根目录"
              className="management-select"
              options={state.folders.map((folder) => ({
                value: folder.id,
                label: folder.name,
                disabled: folder.id === editing?.id,
              }))}
            />
          </Form.Item>
          <Button
            htmlType="submit"
            type="primary"
            icon={<FolderAddOutlined />}
            loading={state.pending}
          >
            {editing ? '保存目录' : '新建目录'}
          </Button>
          {editing && <Button onClick={cancelEditing}>取消</Button>}
        </Form>
      )}
      <Table
        rowKey="id"
        size="small"
        loading={state.foldersLoading}
        pagination={false}
        dataSource={state.folders}
        columns={[
          { title: '目录', dataIndex: 'name' },
          {
            title: '父目录',
            dataIndex: 'parent_id',
            render: (parentId) =>
              state.folders.find((folder) => folder.id === parentId)?.name ?? '根目录',
          },
          {
            title: '操作',
            width: 120,
            render: (_, folder) =>
              canEdit ? (
                <Space>
                  <Button
                    type="text"
                    icon={<EditOutlined />}
                    aria-label="编辑目录"
                    onClick={() => beginEditing(folder)}
                  />
                  <Popconfirm
                    title="删除目录会级联删除子目录，确认继续？"
                    onConfirm={() => state.run(() => deleteFolder(state.projectId, folder.id))}
                  >
                    <Button type="text" danger icon={<DeleteOutlined />} aria-label="删除目录" />
                  </Popconfirm>
                </Space>
              ) : null,
          },
        ]}
      />
    </Space>
  )
}

function ConfigurationManagement({ state, canEdit }: { state: AssetState; canEdit: boolean }) {
  const [form] = Form.useForm<{ variables: string; headers: string }>()
  const configuration = state.configuration
  return (
    <Form
      form={form}
      layout="vertical"
      key={configuration ? JSON.stringify(configuration) : 'loading'}
      initialValues={{
        variables: formatRecord(configuration?.variables),
        headers: formatRecord(configuration?.headers),
      }}
      onFinish={(values) =>
        state.run(() =>
          updateProjectConfiguration(state.projectId, {
            variables: parseRecord(values.variables),
            headers: parseRecord(values.headers),
          }),
        )
      }
    >
      <Form.Item name="variables" label="项目变量（JSON）" rules={[jsonRecordRule]}>
        <Input.TextArea rows={6} className="code-input" readOnly={!canEdit} />
      </Form.Item>
      <Form.Item name="headers" label="项目 Header（JSON）" rules={[jsonRecordRule]}>
        <Input.TextArea rows={6} className="code-input" readOnly={!canEdit} />
      </Form.Item>
      {canEdit && (
        <Button htmlType="submit" type="primary" loading={state.pending}>
          保存项目配置
        </Button>
      )}
    </Form>
  )
}

function EnvironmentManagement({ state, canEdit }: { state: AssetState; canEdit: boolean }) {
  const [environmentId, setEnvironmentId] = useState<string | null>(null)
  const [form] = Form.useForm<EnvironmentFields>()
  const selected = state.environments.find((item) => item.id === environmentId)
  function selectEnvironment(value: string | null) {
    setEnvironmentId(value)
    const environment = state.environments.find((item) => item.id === value)
    form.setFieldsValue(environmentFields(environment))
  }
  function save(values: EnvironmentFields) {
    const input = {
      name: values.name,
      base_url: values.base_url,
      classification: values.classification,
      variables: parseRecord(values.variables),
      headers: parseRecord(values.headers),
    }
    state.run(() =>
      selected
        ? updateEnvironment(state.projectId, selected.id, input)
        : createEnvironment(state.projectId, input),
    )
  }
  return (
    <Space orientation="vertical" className="full-width">
      <Select
        allowClear
        loading={state.environmentsLoading}
        placeholder="新建环境"
        className="management-select"
        value={environmentId}
        onChange={(value) => selectEnvironment(value ?? null)}
        options={state.environments.map((item) => ({ value: item.id, label: item.name }))}
      />
      <Form form={form} layout="vertical" onFinish={save} initialValues={environmentFields()}>
        <Space wrap className="full-width" align="start">
          <Form.Item name="name" label="环境名称" rules={[{ required: true }]}>
            <Input readOnly={!canEdit} />
          </Form.Item>
          <Form.Item name="base_url" label="基础 URL" rules={[{ required: true, type: 'url' }]}>
            <Input className="environment-url-input" readOnly={!canEdit} />
          </Form.Item>
          <Form.Item name="classification" label="环境分类" rules={[{ required: true }]}>
            <Select
              className="management-select"
              disabled={!canEdit}
              options={[
                { value: 'unclassified', label: '未分类（禁止预览）' },
                { value: 'test', label: 'Test' },
                { value: 'sandbox', label: 'Sandbox' },
                { value: 'staging', label: 'Staging（禁止预览）' },
                { value: 'production', label: 'Production（永久禁止预览）' },
              ]}
            />
          </Form.Item>
        </Space>
        <Form.Item name="variables" label="环境变量（JSON）" rules={[jsonRecordRule]}>
          <Input.TextArea rows={5} className="code-input" readOnly={!canEdit} />
        </Form.Item>
        <Form.Item name="headers" label="环境 Header（JSON）" rules={[jsonRecordRule]}>
          <Input.TextArea rows={5} className="code-input" readOnly={!canEdit} />
        </Form.Item>
        {canEdit && (
          <Button htmlType="submit" type="primary" loading={state.pending}>
            {selected ? '更新环境' : '创建环境'}
          </Button>
        )}
      </Form>
    </Space>
  )
}

type EnvironmentFields = {
  name: string
  base_url: string
  classification: NonNullable<Environment['classification']>
  variables: string
  headers: string
}

function SecretManagement({ state, canEdit }: { state: AssetState; canEdit: boolean }) {
  const [form] = Form.useForm<{ name: string; value: string; environment_id: string | null }>()
  return (
    <Space orientation="vertical" className="full-width">
      {canEdit && (
        <Form
          form={form}
          layout="inline"
          initialValues={{ environment_id: null }}
          onFinish={(values) => state.run(() => writeSecret(state.projectId, values))}
        >
          <Form.Item name="name" rules={[{ required: true, pattern: /^[A-Za-z_][\w.-]*$/ }]}>
            <Input placeholder="Secret 名称" prefix={<KeyOutlined />} />
          </Form.Item>
          <Form.Item name="value" rules={[{ required: true }]}>
            <Input.Password placeholder="仅写入，不可读回" />
          </Form.Item>
          <Form.Item name="environment_id">
            <Select
              allowClear
              placeholder="全项目"
              className="management-select"
              options={state.environments.map((item) => ({ value: item.id, label: item.name }))}
            />
          </Form.Item>
          <Button htmlType="submit" type="primary" loading={state.pending}>
            写入 Secret
          </Button>
        </Form>
      )}
      <Table
        rowKey="id"
        size="small"
        loading={state.secretsLoading}
        pagination={false}
        dataSource={state.secrets}
        columns={[
          { title: '名称', dataIndex: 'name' },
          {
            title: '范围',
            dataIndex: 'environment_id',
            render: (environmentId) =>
              environmentId ? (
                (state.environments.find((item) => item.id === environmentId)?.name ??
                environmentId)
              ) : (
                <Tag>全项目</Tag>
              ),
          },
          { title: '值', render: () => <Tag color="green">已加密 · 不可读回</Tag> },
        ]}
      />
    </Space>
  )
}

const jsonRecordRule = {
  validator: (_: unknown, value: string) => {
    try {
      parseRecord(value)
      return Promise.resolve()
    } catch {
      return Promise.reject(new Error('请输入字符串键值对 JSON 对象'))
    }
  },
}

function parseRecord(value = '{}'): Record<string, string> {
  const parsed: unknown = JSON.parse(value || '{}')
  if (
    typeof parsed !== 'object' ||
    parsed === null ||
    Array.isArray(parsed) ||
    !Object.values(parsed).every((item) => typeof item === 'string')
  ) {
    throw new Error('Expected string record')
  }
  return parsed as Record<string, string>
}

function formatRecord(value: Record<string, string> | undefined): string {
  return JSON.stringify(value ?? {}, null, 2)
}

function environmentFields(environment?: Environment): EnvironmentFields {
  return {
    name: environment?.name ?? '',
    base_url: environment?.base_url ?? '',
    classification: environment?.classification ?? 'unclassified',
    variables: formatRecord(environment?.variables),
    headers: formatRecord(environment?.headers),
  }
}
