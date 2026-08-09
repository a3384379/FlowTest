import { DownloadOutlined, InboxOutlined } from '@ant-design/icons'
import { Button, Card, Table, Tag, Upload } from 'antd'

import type { Artifact } from '../../lib/api'

type ArtifactPanelProps = {
  disabled: boolean
  loading: boolean
  uploading: boolean
  items: Artifact[]
  onUpload: (file: File) => Promise<Artifact>
  onDownload: (artifactId: string) => Promise<void>
}

export default function ArtifactPanel(props: ArtifactPanelProps) {
  return (
    <Card
      className="artifact-card"
      title="文件仓库"
      extra={
        <Upload
          showUploadList={false}
          disabled={props.disabled}
          beforeUpload={(file) => {
            void props.onUpload(file)
            return false
          }}
        >
          <Button icon={<InboxOutlined />} disabled={props.disabled} loading={props.uploading}>
            上传文件
          </Button>
        </Upload>
      }
    >
      <Table
        rowKey="id"
        size="small"
        loading={props.loading}
        pagination={false}
        dataSource={props.items}
        locale={{ emptyText: '暂无文件，可上传后用于 multipart 请求' }}
        columns={[
          { title: '文件名', dataIndex: 'filename' },
          { title: '类型', dataIndex: 'content_type' },
          {
            title: '大小',
            dataIndex: 'size_bytes',
            width: 110,
            render: (size: number) => formatBytes(size),
          },
          {
            title: '用途',
            dataIndex: 'purpose',
            width: 90,
            render: (purpose: Artifact['purpose']) => (
              <Tag color={purpose === 'upload' ? 'blue' : 'purple'}>
                {purpose === 'upload' ? '上传' : '响应'}
              </Tag>
            ),
          },
          {
            title: '操作',
            width: 90,
            render: (_: unknown, artifact: Artifact) => (
              <Button
                type="link"
                icon={<DownloadOutlined />}
                onClick={() => props.onDownload(artifact.id)}
              >
                下载
              </Button>
            ),
          },
        ]}
      />
    </Card>
  )
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
