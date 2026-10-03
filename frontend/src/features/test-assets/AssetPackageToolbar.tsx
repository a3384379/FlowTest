import { DownloadOutlined, UploadOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { Alert, App, Button, Space, Typography } from 'antd'
import { useState } from 'react'
import { apiErrorMessage } from '../../lib/api'
import AssetPackageDialog, { type AssetPackageResources } from './AssetPackageDialog'
import { exportAssetPackage } from './asset-package-service'

export default function AssetPackageToolbar({
  projectId,
  canEdit,
  caseIds,
  suiteIds,
  resources,
  onImported,
}: {
  projectId: string
  canEdit: boolean
  caseIds: string[]
  suiteIds: string[]
  resources: AssetPackageResources
  onImported: () => void
}) {
  const { message } = App.useApp()
  const [open, setOpen] = useState(false)
  const download = useMutation({
    mutationFn: () => exportAssetPackage(projectId, caseIds, suiteIds),
  })
  const count = caseIds.length + suiteIds.length
  return (
    <Space orientation="vertical" className="full-width">
      <Space wrap>
        <Button icon={<UploadOutlined />} disabled={!canEdit} onClick={() => setOpen(true)}>
          导入原生包
        </Button>
        <Button
          icon={<DownloadOutlined />}
          disabled={!count}
          loading={download.isPending}
          onClick={() => download.mutate()}
        >
          导出所选 ({count})
        </Button>
        <Typography.Text type="secondary">套件导出会包含全部依赖用例和固定版本。</Typography.Text>
      </Space>
      {download.error && (
        <Alert type="error" title="原生包导出失败" description={apiErrorMessage(download.error)} />
      )}
      {open && (
        <AssetPackageDialog
          projectId={projectId}
          canEdit={canEdit}
          resources={resources}
          onClose={() => setOpen(false)}
          onImported={(result) => {
            void message.success(`已处理 ${result.assets.length} 个测试资产`)
            setOpen(false)
            onImported()
          }}
        />
      )}
    </Space>
  )
}
