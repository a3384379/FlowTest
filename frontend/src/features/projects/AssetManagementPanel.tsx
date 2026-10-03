import { DeleteOutlined, EditOutlined, FolderAddOutlined, KeyOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useRef, useState } from 'react'

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
import { useAuthStore } from '../auth/auth-store'

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
    runAsync: mutation.mutateAsync,
  }
}

type AssetState = ReturnType<typeof useAssetManagement>

type FolderManagementState = Pick<
  AssetState,
  'projectId' | 'folders' | 'foldersLoading' | 'pending' | 'run' | 'runAsync'
>

export function FolderManagementPanel({
  projectId,
  canEdit,
  onRemoved,
}: {
  projectId: string
  canEdit: boolean
  onRemoved?: (ids: string[]) => void
}) {
  const { message } = App.useApp()
  const client = useQueryClient()
  const folders = useQuery({
    queryKey: ['folders', projectId],
    queryFn: () => listFolders(projectId),
  })
  const mutation = useMutation({
    mutationFn: (operation: () => Promise<unknown>) => operation(),
    onSuccess: async () => {
      await Promise.all(
        [
          'folders',
          'test-cases',
          'test-suites',
          'test-case-options',
          'asset-directory-counts',
          'apis',
          'workflows',
          'project-audit',
        ].map((key) => client.invalidateQueries({ queryKey: [key, projectId] })),
      )
      void message.success('目录已更新')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const state: FolderManagementState = {
    projectId,
    folders: folders.data ?? [],
    foldersLoading: folders.isPending,
    pending: mutation.isPending,
    run: mutation.mutate,
    runAsync: mutation.mutateAsync,
  }
  return (
    <>
      <Typography.Paragraph type="secondary">
        目录由当前项目的接口、流程和测试资产共同使用。删除目录后，关联资产归为未分类，历史版本和报告保留。
      </Typography.Paragraph>
      {folders.error && (
        <Alert
          type="error"
          title="目录读取失败"
          description={apiErrorMessage(folders.error)}
          action={<Button onClick={() => void folders.refetch()}>重新加载目录</Button>}
        />
      )}
      <FolderManagement state={state} canEdit={canEdit} onRemoved={onRemoved} />
    </>
  )
}

function FolderManagement({
  state,
  canEdit,
  onRemoved,
}: {
  state: FolderManagementState
  canEdit: boolean
  onRemoved?: (ids: string[]) => void
}) {
  const [editing, setEditing] = useState<Folder | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [form] = Form.useForm<{ name: string; parent_id: string | null }>()
  const blockedParentIds = editing ? folderSubtreeIds(editing.id, state.folders) : []
  async function save(values: { name: string; parent_id: string | null }) {
    const operation = editing
      ? () => updateFolder(state.projectId, editing.id, values)
      : () => createFolder(state.projectId, values)
    setSaveError(null)
    try {
      await state.runAsync(operation)
      setEditing(null)
      form.resetFields()
    } catch (error) {
      setSaveError(apiErrorMessage(error))
    }
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
          <Form.Item
            name="name"
            rules={[
              { required: true, message: '请输入目录名' },
              { max: 160, message: '目录名称最多 160 个字符' },
            ]}
          >
            <Input aria-label="目录名称" placeholder="目录名称" />
          </Form.Item>
          <Form.Item name="parent_id">
            <Select
              allowClear
              aria-label="父目录"
              placeholder="根目录"
              className="management-select"
              options={state.folders.map((folder) => ({
                value: folder.id,
                label: folder.name,
                disabled: blockedParentIds.includes(folder.id),
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
      {saveError && <Alert type="error" title="目录保存失败" description={saveError} />}
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
                  <FolderDeleteAction state={state} folder={folder} onRemoved={onRemoved} />
                </Space>
              ) : null,
          },
        ]}
      />
    </Space>
  )
}

function folderSubtreeIds(rootId: string, folders: Folder[]): string[] {
  const selected = new Set([rootId])
  const pending = [rootId]
  for (let index = 0; index < pending.length; index++) {
    for (const folder of folders) {
      if (folder.parent_id === pending[index] && !selected.has(folder.id)) {
        selected.add(folder.id)
        pending.push(folder.id)
      }
    }
  }
  return pending
}

function FolderDeleteAction({
  state,
  folder,
  onRemoved,
}: {
  state: FolderManagementState
  folder: Folder
  onRemoved?: (ids: string[]) => void
}) {
  const ids = folderSubtreeIds(folder.id, state.folders)
  return (
    <Popconfirm
      title={`删除目录「${folder.name}」及 ${ids.length - 1} 个子目录？`}
      description={
        <div>
          关联接口、流程和测试资产将归为未分类。
          <ul>
            {state.folders
              .filter((item) => ids.includes(item.id))
              .map((item) => (
                <li key={item.id}>
                  {item.name} · {item.id}
                </li>
              ))}
          </ul>
        </div>
      }
      okText="确认删除目录"
      cancelText="取消"
      disabled={state.pending}
      onConfirm={() =>
        state.run(async () => {
          await deleteFolder(state.projectId, folder.id)
          onRemoved?.(ids)
        })
      }
    >
      <Button
        type="text"
        danger
        disabled={state.pending}
        icon={<DeleteOutlined />}
        aria-label={`删除目录 ${folder.name}`}
      />
    </Popconfirm>
  )
}

function ConfigurationManagement({ state, canEdit }: { state: AssetState; canEdit: boolean }) {
  const [form] = Form.useForm<{ variables: string; headers: string }>()
  const [hasDraft, setHasDraft] = useState(false)
  const [draftStorageError, setDraftStorageError] = useState(false)
  const editVersionRef = useRef(0)
  const memoryDraftRef = useRef<{ variables: string; headers: string } | null>(null)
  const draftIdentityRef = useRef<string | null>(null)
  const configuration = state.configuration
  const userId = useAuthStore((store) => store.user?.id)
  const storageKey = userId
    ? `flowtest:project-variables-draft:v1:${userId}:${state.projectId}`
    : null
  useEffect(() => {
    if (!configuration) return
    if (draftIdentityRef.current !== storageKey) {
      draftIdentityRef.current = storageKey
      editVersionRef.current = 0
      memoryDraftRef.current = null
    }
    let active = true
    let hasStoredDraft = false
    let storageFailed = false
    const serverValues = {
      variables: formatRecord(configuration.variables),
      headers: formatRecord(configuration.headers),
    }
    if (memoryDraftRef.current) {
      hasStoredDraft = true
      form.setFieldsValue(memoryDraftRef.current)
    } else if (!storageKey) {
      form.setFieldsValue(serverValues)
    } else {
      try {
        const stored: unknown = JSON.parse(window.localStorage.getItem(storageKey) ?? 'null')
        if (isConfigurationDraft(stored)) {
          hasStoredDraft = true
          form.setFieldsValue(stored)
        } else {
          form.setFieldsValue(serverValues)
        }
      } catch {
        form.setFieldsValue(serverValues)
        storageFailed = true
      }
    }
    queueMicrotask(() => {
      if (!active) return
      setHasDraft(hasStoredDraft)
      setDraftStorageError(storageFailed)
    })
    return () => {
      active = false
    }
  }, [configuration, form, storageKey])
  useEffect(() => {
    if (!hasDraft || !draftStorageError) return
    const blockUnload = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', blockUnload)
    return () => window.removeEventListener('beforeunload', blockUnload)
  }, [draftStorageError, hasDraft])
  return (
    <Form
      form={form}
      layout="vertical"
      onValuesChange={(_, values) => {
        editVersionRef.current += 1
        memoryDraftRef.current = values
        setHasDraft(true)
        if (!storageKey) return
        try {
          window.localStorage.setItem(storageKey, JSON.stringify(values))
          setDraftStorageError(false)
        } catch {
          setDraftStorageError(true)
        }
      }}
      onFinish={async (values) => {
        const editVersionAtStart = editVersionRef.current
        const identityAtStart = storageKey
        await state.runAsync(() =>
          updateProjectConfiguration(state.projectId, {
            variables: parseRecord(values.variables),
            headers: parseRecord(values.headers),
          }),
        )
        if (
          draftIdentityRef.current !== identityAtStart ||
          editVersionRef.current !== editVersionAtStart
        ) {
          return
        }
        let removed = true
        if (storageKey) {
          try {
            window.localStorage.removeItem(storageKey)
          } catch {
            removed = false
          }
        }
        if (removed) memoryDraftRef.current = null
        setHasDraft(!removed)
        setDraftStorageError(!removed)
      }}
    >
      <Form.Item name="variables" label="项目变量（JSON）" rules={[jsonRecordRule]}>
        <Input.TextArea rows={6} className="code-input" readOnly={!canEdit} />
      </Form.Item>
      <Form.Item name="headers" label="项目 Header（JSON）" rules={[jsonRecordRule]}>
        <Input.TextArea rows={6} className="code-input" readOnly={!canEdit} />
      </Form.Item>
      <Space wrap>
        {canEdit && (
          <Button htmlType="submit" type="primary" loading={state.pending}>
            保存项目配置
          </Button>
        )}
        {hasDraft && <Tag color="orange">本地未保存</Tag>}
        {draftStorageError && <Tag color="red">浏览器无法持久化草稿，请先保存再离开</Tag>}
      </Space>
    </Form>
  )
}

function isConfigurationDraft(value: unknown): value is { variables: string; headers: string } {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { variables?: unknown }).variables === 'string' &&
    typeof (value as { headers?: unknown }).headers === 'string'
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
