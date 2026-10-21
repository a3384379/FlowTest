import { DeleteOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App, Button, Popconfirm, Space, Switch, Table, Tabs, Typography } from 'antd'
import { useLayoutEffect, useRef, useState } from 'react'

import CatalogPagination from '../../components/CatalogPagination'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { apiErrorWithTrace, type MockRoute, type MockService } from '../../lib/api'
import { useCatalogQuery } from '../../lib/catalog-query'
import {
  createMockRoute,
  deleteMockRoute,
  listMockLogs,
  listMockRoutes,
  updateMockRoute,
  type MockRouteInput,
} from './data-source-service'
import MockRouteForm from './MockRouteForm'

type WorkspaceProps = {
  projectId: string
  service: MockService
  canEdit: boolean
  readable?: boolean
  onDirtyChange?: (dirty: boolean) => void
}

export default function MockRouteWorkspace(props: WorkspaceProps) {
  return <ScopedMockRouteWorkspace key={`${props.projectId}:${props.service.id}`} {...props} />
}

function useMockRouteWorkspaceState({
  projectId,
  service,
  canEdit,
  readable = true,
  onDirtyChange,
}: WorkspaceProps) {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const active = useRef(true)
  useLayoutEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  const [selected, setSelected] = useState<MockRoute | null>(null)
  const [revision, setRevision] = useState(0)
  const [dirty, setDirty] = useState(false)
  function changeDirty(value: boolean) {
    setDirty(value)
    onDirtyChange?.(value)
  }
  function selectRoute(route: MockRoute | null) {
    setSelected(route)
    setRevision((value) => value + 1)
    changeDirty(false)
  }
  function requestSelection(route: MockRoute | null) {
    if (!dirty) {
      selectRoute(route)
      return
    }
    modal.confirm({
      title: '切换规则前放弃未保存修改？',
      content: '当前输入尚未保存，切换后将重新加载所选规则。',
      okText: '放弃并切换',
      cancelText: '继续编辑',
      onOk: () => selectRoute(route),
    })
  }
  const routes = useQuery({
    queryKey: ['mock-routes', projectId, service.id],
    queryFn: () => listMockRoutes(projectId, service.id),
  })
  const logs = useCatalogQuery(
    'mock-logs',
    projectId,
    (page) => listMockLogs(projectId, service.id, page, 20),
    true,
    service.id,
    { refetchInterval: 2_000 },
  )
  const saveRouteMutation = useMutation({
    mutationFn: (input: MockRouteInput) =>
      selected
        ? updateMockRoute(projectId, service.id, selected.id, input)
        : createMockRoute(projectId, service.id, input),
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: ['mock-routes', projectId, service.id] })
      if (!active.current) return
      selectRoute(saved)
      void message.success('Mock 路由已保存')
    },
    onError: (error) => {
      if (active.current) void message.error(apiErrorWithTrace(error))
    },
  })
  const toggleRouteMutation = useMutation({
    mutationFn: (input: { route: MockRoute; enabled: boolean }) =>
      updateMockRoute(projectId, service.id, input.route.id, {
        ...routeInput(input.route),
        is_enabled: input.enabled,
      }),
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: ['mock-routes', projectId, service.id] })
      if (!active.current) return
      if (selected?.id === saved.id && !dirty) selectRoute(saved)
    },
    onError: (error) => {
      if (active.current) void message.error(apiErrorWithTrace(error))
    },
  })
  const removeRouteMutation = useMutation({
    mutationFn: (routeId: string) => deleteMockRoute(projectId, service.id, routeId),
    onSuccess: async (_result, routeId) => {
      await queryClient.invalidateQueries({ queryKey: ['mock-routes', projectId, service.id] })
      if (active.current && selected?.id === routeId) selectRoute(null)
    },
    onError: (error) => {
      if (active.current) void message.error(apiErrorWithTrace(error))
    },
  })
  const pending =
    saveRouteMutation.isPending || toggleRouteMutation.isPending || removeRouteMutation.isPending
  const showEditor = canEdit || Boolean(selected)
  return {
    projectId,
    serviceId: service.id,
    serviceEnabled: service.is_enabled,
    routes,
    logs,
    selected,
    revision,
    dirty,
    pending,
    showEditor,
    canEdit,
    readable,
    requestSelection,
    saveRouteMutation,
    toggleRouteMutation,
    removeRouteMutation,
    changeDirty,
  }
}

function ScopedMockRouteWorkspace(props: WorkspaceProps) {
  const state = useMockRouteWorkspaceState(props)
  return <MockWorkspaceView state={state} />
}

function MockWorkspaceView({ state }: { state: ReturnType<typeof useMockRouteWorkspaceState> }) {
  const {
    projectId,
    serviceId,
    serviceEnabled,
    routes,
    logs,
    selected,
    revision,
    dirty,
    pending,
    showEditor,
    canEdit,
    readable,
    requestSelection,
    saveRouteMutation,
    toggleRouteMutation,
    removeRouteMutation,
    changeDirty,
  } = state
  return (
    <div className="mock-route-workspace">
      <div>
        <QueryFailureNotice queries={[routes, logs]} />
        <Space wrap>
          {canEdit && (
            <Button disabled={pending} onClick={() => requestSelection(null)}>
              新建规则
            </Button>
          )}
          <Typography.Text type="secondary">启停仅影响后续请求匹配</Typography.Text>
        </Space>
        <CatalogPagination query={logs} label="Mock 请求日志" />
        <Tabs
          items={[
            {
              key: 'routes',
              label: '路由规则',
              children: (
                <Table
                  rowKey="id"
                  size="small"
                  loading={routes.isLoading}
                  dataSource={routes.data ?? []}
                  locale={{ emptyText: routes.isError ? '路由读取失败，请重试' : '无路由规则' }}
                  scroll={{ x: 800 }}
                  pagination={false}
                  columns={[
                    {
                      title: '名称',
                      render: (_, item) => (
                        <Button
                          type="link"
                          disabled={pending}
                          aria-label={`${canEdit ? '编辑' : '查看'} Mock 路由：${item.name}`}
                          onClick={() => requestSelection(item)}
                        >
                          {item.name}
                        </Button>
                      ),
                    },
                    { title: '方法', dataIndex: 'method' },
                    { title: '路径', dataIndex: 'path_pattern' },
                    { title: '场景', dataIndex: 'scenario', render: (value) => value || '默认' },
                    { title: '状态码', dataIndex: 'response_status' },
                    { title: '优先级', dataIndex: 'priority' },
                    {
                      title: '启用',
                      render: (_, item) => (
                        <Switch
                          aria-label={`启用规则：${item.name}`}
                          checked={item.is_enabled}
                          disabled={
                            !canEdit ||
                            !readable ||
                            !routes.isSuccess ||
                            pending ||
                            (dirty && selected?.id === item.id)
                          }
                          onChange={(enabled) =>
                            toggleRouteMutation.mutate({ route: item, enabled })
                          }
                        />
                      ),
                    },
                    {
                      title: '操作',
                      render: (_, item) =>
                        canEdit ? (
                          <Popconfirm
                            title="确认删除路由？"
                            description="该路由将不再匹配，未保存的修改也会丢弃。"
                            onConfirm={() => removeRouteMutation.mutate(item.id)}
                          >
                            <Button
                              type="text"
                              danger
                              disabled={pending || !readable || !routes.isSuccess}
                              icon={<DeleteOutlined />}
                              aria-label="删除 Mock 路由"
                            />
                          </Popconfirm>
                        ) : null,
                    },
                  ]}
                />
              ),
            },
            {
              key: 'logs',
              label: '请求日志',
              children: <MockLogsTable logs={logs} />,
            },
          ]}
        />
      </div>
      {showEditor && (
        <MockRouteForm
          key={`${selected?.id ?? 'new'}:${revision}`}
          projectId={projectId}
          serviceId={serviceId}
          route={selected}
          canEdit={canEdit}
          readable={readable && routes.isSuccess}
          pending={pending}
          previewScope={`${serviceEnabled}:${routes.dataUpdatedAt}`}
          onDirty={() => changeDirty(true)}
          onFinish={saveRouteMutation.mutate}
        />
      )}
    </div>
  )
}

function MockLogsTable({ logs }: { logs: ReturnType<typeof useMockRouteWorkspaceState>['logs'] }) {
  return (
    <Table
      rowKey="id"
      size="small"
      loading={logs.isLoading}
      dataSource={logs.data?.items ?? []}
      columns={[
        { title: '时间', dataIndex: 'created_at' },
        { title: '方法', dataIndex: 'method' },
        { title: '路径', dataIndex: 'path' },
        {
          title: '匹配',
          dataIndex: 'matched',
          render: (value) => (value ? '是' : '否'),
        },
        { title: '状态码', dataIndex: 'response_status' },
        { title: '耗时', dataIndex: 'duration_ms', render: (value) => `${value} ms` },
      ]}
    />
  )
}

function routeInput(route: MockRoute): MockRouteInput {
  return {
    name: route.name,
    method: route.method,
    path_pattern: route.path_pattern,
    query_conditions: route.query_conditions,
    header_conditions: route.header_conditions,
    response_status: route.response_status,
    response_headers: route.response_headers,
    response_body: route.response_body,
    delay_ms: route.delay_ms,
    scenario: route.scenario,
    priority: route.priority,
    is_enabled: route.is_enabled,
  }
}
