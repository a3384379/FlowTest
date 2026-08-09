import { InboxOutlined } from '@ant-design/icons'
import { Alert, Modal, Select, Space, Statistic, Table, Tag, Upload, Typography } from 'antd'
import { useState } from 'react'

import type { ImportChange, ImportRun } from '../../lib/api'

type ImportDialogProps = {
  open: boolean
  importing: boolean
  result: ImportRun | null
  onClose: () => void
  onImport: (file: File) => Promise<ImportRun>
}

const changeLabels: Record<ImportChange, { label: string; color: string }> = {
  added: { label: '新增', color: 'green' },
  changed: { label: '变更', color: 'blue' },
  deleted: { label: '待停用', color: 'red' },
  unchanged: { label: '未变化', color: 'default' },
}

export default function ImportDialog(props: ImportDialogProps) {
  const [file, setFile] = useState<File | null>(null)

  return (
    <Modal
      title="导入接口文档"
      width={820}
      open={props.open}
      confirmLoading={props.importing}
      okText="开始导入"
      okButtonProps={{ disabled: !file || Boolean(props.result) }}
      onCancel={() => {
        setFile(null)
        props.onClose()
      }}
      onOk={() => file && props.onImport(file)}
      destroyOnHidden
    >
      {props.result ? <ImportResult result={props.result} /> : <ImportPicker onChange={setFile} />}
    </Modal>
  )
}

function ImportPicker({ onChange }: { onChange: (file: File) => void }) {
  return (
    <>
      <Alert
        type="info"
        showIcon
        title="支持 OpenAPI 3、Swagger 2 和 Postman Collection"
        description="系统会按请求方法和规范化路径去重，并展示新增、变更、删除和未变化项。"
      />
      <div className="import-format-row">
        <Typography.Text>格式识别</Typography.Text>
        <Select value="auto" disabled options={[{ value: 'auto', label: '自动识别' }]} />
      </div>
      <Upload.Dragger
        accept=".json,.yaml,.yml"
        maxCount={1}
        beforeUpload={(selected) => {
          onChange(selected)
          return false
        }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">点击或拖拽文档到此处</p>
        <p className="ant-upload-hint">单个文件最大 50 MB</p>
      </Upload.Dragger>
    </>
  )
}

function ImportResult({ result }: { result: ImportRun }) {
  return (
    <>
      <Space size="large" className="import-statistics">
        <Statistic title="新增" value={result.added} styles={{ content: { color: '#16a34a' } }} />
        <Statistic title="变更" value={result.changed} styles={{ content: { color: '#2563eb' } }} />
        <Statistic
          title="待停用"
          value={result.deleted}
          styles={{ content: { color: '#dc2626' } }}
        />
        <Statistic title="未变化" value={result.unchanged} />
      </Space>
      <Table
        rowKey="import_key"
        size="small"
        pagination={false}
        dataSource={result.results}
        columns={[
          { title: '接口', dataIndex: 'name' },
          { title: '方法', dataIndex: 'method', width: 90 },
          { title: '路径', dataIndex: 'path' },
          {
            title: 'Diff',
            dataIndex: 'change',
            width: 100,
            render: (change: ImportChange) => (
              <Tag color={changeLabels[change].color}>{changeLabels[change].label}</Tag>
            ),
          },
        ]}
      />
    </>
  )
}
