import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  App,
  Alert,
  Button,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  TreeSelect,
  Typography,
} from 'antd'
import { useState } from 'react'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import { apiErrorMessage, type Folder } from '../../lib/api'
import { listFolders } from '../projects/asset-service'
import { listApiDirectory, moveApis, type ApiDirectoryEntry, type HttpMethod } from './api-service'

function useFolderMove(projectId: string, onMoved: () => void) {
  const client = useQueryClient()
  const { message } = App.useApp()
  return useMutation({
    mutationFn: (input: { ids: string[]; folderId: string | null }) =>
      moveApis(projectId, input.ids, input.folderId),
    onSuccess: async (result) => {
      await Promise.all(
        ['apis', 'api-detail'].map((key) =>
          client.invalidateQueries({ queryKey: [key, projectId] }),
        ),
      )
      onMoved()
      void message.success(`已移动 ${result.moved_count} 个接口`)
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
}

export function MoveApisDialog({
  projectId,
  ids,
  onClose,
  onMoved,
  initialFolderId,
}: {
  projectId: string
  ids: string[]
  onClose: () => void
  onMoved: () => void
  initialFolderId?: string | null
}) {
  const [destination, setDestination] = useState<string | null>(() =>
    initialFolderId === undefined ? null : (initialFolderId ?? 'unfiled'),
  )
  const folders = useQuery({
    queryKey: ['folders', projectId],
    queryFn: () => listFolders(projectId),
  })
  const mutation = useFolderMove(projectId, onMoved)
  return (
    <Modal
      open
      title={`移动 ${ids.length} 个接口`}
      okText="确认移动"
      cancelText="取消"
      confirmLoading={mutation.isPending}
      closable={!mutation.isPending}
      maskClosable={!mutation.isPending}
      keyboard={!mutation.isPending}
      onCancel={onClose}
      okButtonProps={{
        disabled: !ids.length || destination === null || folders.isPending || folders.isError,
      }}
      onOk={() => {
        if (destination !== null)
          mutation.mutate({ ids, folderId: destination === 'unfiled' ? null : destination })
      }}
    >
      <QueryFailureNotice queries={[folders]} />
      <Typography.Paragraph>
        只更改分组归属，接口版本、用例引用和历史记录会保留。
      </Typography.Paragraph>
      <TreeSelect
        aria-label="接口目标分组"
        className="full-width"
        treeDefaultExpandAll
        value={destination ?? undefined}
        placeholder="请选择目标分组"
        onChange={setDestination}
        disabled={mutation.isPending}
        treeData={[
          { value: 'unfiled', title: '未分组' },
          ...folderTargets(folders.data ?? [], null),
        ]}
      />
      {mutation.isError && (
        <Alert type="error" showIcon title="移动失败，已保留所选接口，可修正后重试。" />
      )}
    </Modal>
  )
}

export function AddApisToFolderDialog({
  projectId,
  folder,
  onClose,
}: {
  projectId: string
  folder: Folder
  onClose: () => void
}) {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [method, setMethod] = useState<HttpMethod>()
  const [ids, setIds] = useState<string[]>([])
  const entries = useQuery({
    queryKey: ['apis', projectId, 'directory', page, search, method],
    queryFn: () => listApiDirectory(projectId, { page, search, method }),
  })
  const folders = useQuery({
    queryKey: ['folders', projectId],
    queryFn: () => listFolders(projectId),
  })
  const mutation = useFolderMove(projectId, onClose)
  const items = entries.data?.items ?? []
  const inPage = ids.filter((id) => items.some((item) => item.id === id)).length
  return (
    <Modal
      open
      title={`添加接口到：${folderPath(folders.data ?? [], folder.id)}`}
      width={800}
      okText={`移入分组（${ids.length}）`}
      cancelText="取消"
      onCancel={onClose}
      closable={!mutation.isPending}
      maskClosable={!mutation.isPending}
      keyboard={!mutation.isPending}
      confirmLoading={mutation.isPending}
      okButtonProps={{ disabled: !ids.length || entries.isError }}
      onOk={() => mutation.mutate({ ids, folderId: folder.id })}
    >
      <QueryFailureNotice queries={[entries, folders]} />
      <Typography.Paragraph type="secondary">
        从项目内选择接口移入此分组；同一接口只属于一个分组。
      </Typography.Paragraph>
      <Space wrap className="api-folder-candidate-filters">
        <Input.Search
          aria-label="搜索待添加接口"
          placeholder="搜索名称、路径或说明"
          allowClear
          value={search}
          disabled={mutation.isPending}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(1)
          }}
        />
        <Select
          aria-label="待添加接口方法"
          allowClear
          placeholder="全部方法"
          value={method}
          disabled={mutation.isPending}
          onChange={(value) => {
            setMethod(value)
            setPage(1)
          }}
          options={['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((value) => ({
            value,
            label: value,
          }))}
        />
        <Typography.Text>
          已选 {ids.length} 个，本页 {inPage} 个，其他页 {ids.length - inPage} 个
        </Typography.Text>
        <Button
          size="small"
          disabled={mutation.isPending || !ids.length}
          onClick={() => setIds([])}
        >
          清空选择
        </Button>
      </Space>
      <Table<ApiDirectoryEntry>
        rowKey="id"
        size="small"
        loading={entries.isFetching}
        dataSource={items}
        rowSelection={{
          selectedRowKeys: ids,
          preserveSelectedRowKeys: true,
          onChange: (keys) => setIds(keys.map(String)),
          getCheckboxProps: (item) => ({
            disabled: mutation.isPending || item.folder_id === folder.id,
            'aria-label': `勾选接口 ${item.name}`,
          }),
        }}
        pagination={{
          current: page,
          total: entries.data?.total ?? 0,
          pageSize: 20,
          showSizeChanger: false,
          onChange: setPage,
        }}
        columns={[
          { title: '接口', dataIndex: 'name' },
          {
            title: '方法 / 路径',
            render: (_, item) => (
              <>
                <Tag>{item.method}</Tag>
                <span>{item.path}</span>
              </>
            ),
          },
          {
            title: '当前分组',
            render: (_, item) =>
              item.folder_id === folder.id ? (
                <Tag>已在此分组</Tag>
              ) : (
                folderPath(folders.data ?? [], item.folder_id)
              ),
          },
        ]}
      />
      {mutation.isError && <Alert type="error" title="移入失败，选择已保留，请刷新核对后重试。" />}
    </Modal>
  )
}

function folderTargets(
  items: Folder[],
  parentId: string | null,
): Array<{ value: string; title: string; children: ReturnType<typeof folderTargets> }> {
  return items
    .filter((item) => item.parent_id === parentId)
    .map((item) => ({
      value: item.id,
      title: folderPath(items, item.id),
      children: folderTargets(items, item.id),
    }))
}

function folderPath(items: Folder[], id: string | null): string {
  if (!id) return '未分组'
  const parts: string[] = []
  const visited = new Set<string>()
  let current = items.find((item) => item.id === id)
  while (current && !visited.has(current.id)) {
    visited.add(current.id)
    parts.unshift(current.name)
    current = items.find((item) => item.id === current?.parent_id)
  }
  return parts.join(' / ') || '分组已失效'
}
