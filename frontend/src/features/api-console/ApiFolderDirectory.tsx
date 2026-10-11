import { FolderAddOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App, Button, Modal, Select, Space, Tree } from 'antd'
import { useState } from 'react'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import { apiErrorMessage, type ApiDefinition, type Folder } from '../../lib/api'
import { listFolders } from '../projects/asset-service'
import { FolderManagementPanel } from '../projects/AssetManagementPanel'
import { updateApiDefinition } from './api-service'

type Props = {
  projectId: string
  editable: boolean
  selected: string
  definition?: ApiDefinition
  onSelect: (id: string) => void
}

export default function ApiFolderDirectory(props: Props) {
  const { message } = App.useApp()
  const client = useQueryClient()
  const folders = useQuery({
    queryKey: ['folders', props.projectId],
    queryFn: () => listFolders(props.projectId),
  })
  const [managementOpen, setManagementOpen] = useState(false)
  const [moving, setMoving] = useState<ApiDefinition | null>(null)
  const [destination, setDestination] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: ({ id, folderId }: { id: string; folderId: string | null }) =>
      updateApiDefinition(props.projectId, id, { folder_id: folderId }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['apis', props.projectId] }),
        client.invalidateQueries({ queryKey: ['api-detail', props.projectId] }),
      ])
      setMoving(null)
      void message.success('接口已移动')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  return (
    <div className="api-folder-directory">
      <QueryFailureNotice queries={[folders]} />
      <Space wrap>
        <Button
          size="small"
          icon={<FolderAddOutlined />}
          disabled={!props.editable}
          onClick={() => setManagementOpen(true)}
        >
          管理分组
        </Button>
        <Button
          size="small"
          disabled={!props.editable || !props.definition || mutation.isPending}
          onClick={() => {
            setMoving(props.definition ?? null)
            setDestination(props.definition?.folder_id ?? null)
          }}
        >
          移动接口
        </Button>
      </Space>
      <Tree
        aria-label="接口分组树"
        blockNode
        showLine
        selectedKeys={[props.selected]}
        onSelect={(keys) => {
          if (keys[0]) props.onSelect(String(keys[0]))
        }}
        treeData={[
          { key: 'all', title: '全部接口' },
          { key: 'unfiled', title: '未分组' },
          ...folderNodes(folders.data ?? [], null),
        ]}
      />
      <Modal
        open={managementOpen}
        title="管理接口分组"
        footer={null}
        onCancel={() => setManagementOpen(false)}
        width={760}
        destroyOnHidden
      >
        <FolderManagementPanel
          projectId={props.projectId}
          canEdit={props.editable}
          onRemoved={(ids) => {
            if (ids.includes(props.selected)) props.onSelect('unfiled')
          }}
        />
      </Modal>
      <Modal
        open={moving !== null}
        title={`移动接口：${moving?.name ?? ''}`}
        okText="移动"
        cancelText="取消"
        confirmLoading={mutation.isPending}
        onCancel={() => setMoving(null)}
        onOk={() => {
          if (moving) mutation.mutate({ id: moving.id, folderId: destination })
        }}
      >
        <Select
          aria-label="接口目标分组"
          className="full-width"
          value={destination ?? 'unfiled'}
          onChange={(value) => setDestination(value === 'unfiled' ? null : value)}
          options={[
            { value: 'unfiled', label: '未分组' },
            ...(folders.data ?? []).map((item) => ({ value: item.id, label: item.name })),
          ]}
        />
      </Modal>
    </div>
  )
}

function folderNodes(
  items: Folder[],
  parentId: string | null,
): Array<{ key: string; title: string; children: ReturnType<typeof folderNodes> }> {
  return items
    .filter((item) => item.parent_id === parentId)
    .map((item) => ({ key: item.id, title: item.name, children: folderNodes(items, item.id) }))
}
