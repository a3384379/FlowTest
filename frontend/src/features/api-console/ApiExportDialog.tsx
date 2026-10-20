import { useQuery } from '@tanstack/react-query'
import { Form, Modal, Select, Typography } from 'antd'
import { useState } from 'react'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import { apiErrorMessage } from '../../lib/api'
import { listFolders } from '../projects/asset-service'
import { listApis, type ApiExportFormat, type ApiExportRequest } from './api-service'

type Scope = ApiExportRequest['scope']
type Props = {
  projectId: string
  folder: string
  selectedIds: string[]
  exporting: boolean
  onExport: (request: ApiExportRequest) => Promise<void>
  onClose: () => void
}

function useExportScope(props: Props) {
  const [scope, setScope] = useState<Scope>('project')
  const [format, setFormat] = useState<ApiExportFormat>('har')
  const [error, setError] = useState<string | null>(null)
  const count = useQuery({
    queryKey: ['api-export-count', props.projectId, scope, props.folder],
    queryFn: () =>
      listApis(props.projectId, {
        pageSize: 1,
        folder: scope === 'folder' ? props.folder : 'all',
      }),
    enabled: scope !== 'selected',
  })
  const folders = useQuery({
    queryKey: ['folders', props.projectId],
    queryFn: () => listFolders(props.projectId),
  })
  const folderName = exportFolderName(props.folder, folders.data)
  const labels: Record<Scope, string> = {
    project: '整个项目',
    folder: `当前分组：${folderName}（仅本级，不含子分组）`,
    selected: '已选接口（包含其他页保留的选择）',
  }
  const total = scope === 'selected' ? props.selectedIds.length : count.data?.total
  const selectionInvalid = scope === 'selected' && (!total || total > 1000)
  const pendingCount = scope !== 'selected' && (count.isPending || count.isError)

  async function download() {
    if (selectionInvalid || pendingCount || props.exporting) return
    setError(null)
    const selection = exportSelection(scope, props.folder, props.selectedIds)
    try {
      await props.onExport({ format, ...selection })
      props.onClose()
    } catch (failure) {
      setError(apiErrorMessage(failure))
    }
  }

  return {
    scope,
    setScope,
    format,
    setFormat,
    error,
    labels,
    total,
    count,
    selectionInvalid,
    pendingCount,
    download,
  }
}

function exportFolderName(
  folder: string,
  folders: Awaited<ReturnType<typeof listFolders>> | undefined,
) {
  if (folder === 'all') return '未选择分组'
  if (folder === 'unfiled') return '未分组'
  return folders?.find((item) => item.id === folder)?.name ?? '当前分组'
}

export default function ApiExportDialog(props: Props) {
  const state = useExportScope(props)
  const {
    scope,
    setScope,
    format,
    setFormat,
    error,
    labels,
    total,
    selectionInvalid,
    pendingCount,
    download,
  } = state
  return (
    <Modal
      title="导出接口资产"
      open
      okText={scope === 'project' ? '导出整个项目' : '导出指定范围'}
      cancelText="取消"
      confirmLoading={props.exporting}
      closable={!props.exporting}
      cancelButtonProps={{ disabled: props.exporting, 'aria-label': '取消' }}
      okButtonProps={{
        disabled: selectionInvalid || pendingCount || props.exporting,
        'aria-label': scope === 'project' ? '导出整个项目' : '导出指定范围',
      }}
      onCancel={() => {
        if (!props.exporting) props.onClose()
      }}
      onOk={() => void download()}
    >
      <Form layout="vertical" disabled={props.exporting}>
        <Form.Item label="导出范围">
          <Select
            aria-label="导出范围"
            value={scope}
            onChange={setScope}
            options={[
              { value: 'project', label: labels.project },
              { value: 'folder', label: labels.folder, disabled: props.folder === 'all' },
              { value: 'selected', label: labels.selected, disabled: !props.selectedIds.length },
            ]}
          />
        </Form.Item>
        <Form.Item label="文件格式">
          <Select
            aria-label="导出格式"
            value={format}
            onChange={setFormat}
            options={['har', 'curl', 'bruno', 'excel'].map((value) => ({
              value,
              label: { har: 'HAR', curl: 'cURL', bruno: 'Bruno', excel: 'Excel' }[value],
            }))}
          />
        </Form.Item>
      </Form>
      <Typography.Paragraph>
        {labels[scope]} · {total === undefined ? '正在读取数量' : `当前共 ${total} 个接口`}
      </Typography.Paragraph>
      <Typography.Paragraph type="secondary">
        使用各接口已保存的当前版本；搜索和方法筛选不影响范围。数量为当前查询结果，下载时由服务器重新校验。
      </Typography.Paragraph>
      <ExportScopeNotice state={state} />
      {error && (
        <Typography.Paragraph role="alert" type="danger">
          {error}
        </Typography.Paragraph>
      )}
    </Modal>
  )
}

function ExportScopeNotice({ state }: { state: ReturnType<typeof useExportScope> }) {
  return (
    <>
      {state.scope === 'selected' && state.selectionInvalid && (
        <Typography.Paragraph role="alert" type="danger">
          所选导出每次需要选择 1 至 1000 个接口，请调整选择。
        </Typography.Paragraph>
      )}
      {state.scope !== 'selected' && <QueryFailureNotice queries={[state.count]} />}
    </>
  )
}

function exportSelection(scope: Scope, folder: string, ids: string[]) {
  if (scope === 'selected') return { scope, definition_ids: [...ids] }
  if (scope === 'folder') {
    return folder === 'unfiled' ? { scope, unfiled: true as const } : { scope, folder_id: folder }
  }
  return { scope }
}
