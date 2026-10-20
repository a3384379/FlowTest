import { TreeSelect } from 'antd'
import type { Folder } from '../../lib/api'

type FolderOption = { value: string; title: string; children: FolderOption[]; disabled?: boolean }

export default function AssetFolderSelect({
  folders,
  value,
  onChange,
  ...props
}: {
  folders: Folder[]
  value?: string | null
  onChange?: (value: string | undefined) => void
  id?: string
  'aria-label'?: string
  placeholder?: string
}) {
  const data = folderOptions(folders, null, [])
  if (value && !folders.some((folder) => folder.id === value))
    data.push({ value, title: '目录已失效，请重新选择', children: [], disabled: true })
  return (
    <TreeSelect
      {...props}
      allowClear
      showSearch
      treeDefaultExpandAll
      treeNodeFilterProp="title"
      placeholder={props.placeholder ?? '未分类'}
      value={value ?? undefined}
      treeData={data}
      onChange={(next?: string) => onChange?.(next)}
      style={{ minWidth: 180, width: '100%' }}
    />
  )
}

function folderOptions(folders: Folder[], parentId: string | null, path: string[]): FolderOption[] {
  return folders
    .filter((folder) => folder.parent_id === parentId)
    .map((folder) => {
      const names = [...path, folder.name]
      return {
        value: folder.id,
        title: names.join(' / '),
        children: folderOptions(folders, folder.id, names),
      }
    })
}
