import { FolderAddOutlined, PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Button, Modal, Space, Tree } from 'antd'
import { useState, type ReactNode } from 'react'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import { type ApiDefinition, type Folder } from '../../lib/api'
import { listFolders } from '../projects/asset-service'
import { FolderManagementPanel } from '../projects/AssetManagementPanel'
import { AddApisToFolderDialog, MoveApisDialog } from './ApiFolderActions'

type Props = {
  projectId: string
  editable: boolean
  selected: string
  definition?: ApiDefinition
  onSelect: (id: string) => void
}

export default function ApiFolderDirectory(props: Props) {
  const folders = useQuery({
    queryKey: ['folders', props.projectId],
    queryFn: () => listFolders(props.projectId),
  })
  const [managementOpen, setManagementOpen] = useState(false)
  const [moving, setMoving] = useState<string[] | null>(null)
  const [adding, setAdding] = useState<Folder | null>(null)
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
          disabled={!props.editable || !props.definition}
          onClick={() => {
            if (props.definition) setMoving([props.definition.id])
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
          ...folderNodes(folders.data ?? [], null, (folder) => (
            <span className="api-folder-title">
              <span>{folder.name}</span>
              <Button
                size="small"
                type="text"
                icon={<PlusOutlined />}
                aria-label={`添加接口到分组 ${folder.name}`}
                disabled={!props.editable}
                onClick={(event) => {
                  event.stopPropagation()
                  setAdding(folder)
                }}
              />
            </span>
          )),
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
      {moving && props.editable && (
        <MoveApisDialog
          projectId={props.projectId}
          ids={moving}
          onClose={() => setMoving(null)}
          onMoved={() => setMoving(null)}
        />
      )}
      {adding && props.editable && (
        <AddApisToFolderDialog
          projectId={props.projectId}
          folder={adding}
          onClose={() => setAdding(null)}
        />
      )}
    </div>
  )
}

function folderNodes(
  items: Folder[],
  parentId: string | null,
  render: (folder: Folder) => ReactNode,
): Array<{ key: string; title: ReactNode; children: ReturnType<typeof folderNodes> }> {
  return items
    .filter((item) => item.parent_id === parentId)
    .map((item) => ({
      key: item.id,
      title: render(item),
      children: folderNodes(items, item.id, render),
    }))
}
