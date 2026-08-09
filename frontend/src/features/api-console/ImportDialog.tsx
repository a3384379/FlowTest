import { InboxOutlined } from '@ant-design/icons'
import { Alert, Modal, Select, Space, Statistic, Table, Tag, Upload, Typography } from 'antd'
import { useState } from 'react'

import type { ImportChange, ImportRun } from '../../lib/api'

type ImportDialogProps = {
  open: boolean
  importing: boolean
  result: ImportRun | null
  onClose: () => void
  onPreview: (file: File) => Promise<ImportRun>
  onMerge: (selectedKeys: string[]) => Promise<ImportRun>
}

const changeLabels: Record<ImportChange, { label: string; color: string }> = {
  added: { label: '新增', color: 'green' },
  changed: { label: '变更', color: 'blue' },
  deleted: { label: '待停用', color: 'red' },
  unchanged: { label: '未变化', color: 'default' },
}

export default function ImportDialog(props: ImportDialogProps) {
  const [file, setFile] = useState<File | null>(null)
  const [selectedKeys, setSelectedKeys] = useState<string[] | null>(null)
  const effectiveSelectedKeys = selectedKeys ?? defaultSelection(props.result)

  const completed = props.result?.status === 'applied'

  return (
    <Modal
      title="导入接口文档"
      width={820}
      open={props.open}
      confirmLoading={props.importing}
      okText={completed ? '完成' : props.result ? '合并所选' : '生成 Diff'}
      okButtonProps={{ disabled: !props.result && !file }}
      onCancel={() => {
        setFile(null)
        setSelectedKeys(null)
        props.onClose()
      }}
      onOk={() => {
        if (completed) {
          setFile(null)
          setSelectedKeys(null)
          props.onClose()
        } else if (props.result) {
          void props.onMerge(effectiveSelectedKeys)
        } else if (file) {
          void props.onPreview(file)
        }
      }}
      destroyOnHidden
    >
      {props.result ? (
        <ImportResult
          result={props.result}
          selectedKeys={effectiveSelectedKeys}
          onSelectionChange={setSelectedKeys}
        />
      ) : (
        <ImportPicker onChange={setFile} />
      )}
    </Modal>
  )
}

function defaultSelection(result: ImportRun | null): string[] {
  if (result?.status !== 'preview') return []
  return result.results
    .filter((item) => item.change === 'added' || item.change === 'changed')
    .map((item) => item.import_key)
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

function ImportResult({
  result,
  selectedKeys,
  onSelectionChange,
}: {
  result: ImportRun
  selectedKeys: string[]
  onSelectionChange: (keys: string[]) => void
}) {
  return (
    <>
      <Alert
        type={result.status === 'applied' ? 'success' : 'warning'}
        showIcon
        title={result.status === 'applied' ? '合并完成' : '请选择需要合并的变更'}
        description={
          result.status === 'applied'
            ? `已应用 ${result.applied_keys.length} 项变更。`
            : '新增和变更默认选中；删除项默认不选中，只有明确选择后才会停用接口。'
        }
      />
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
        rowSelection={
          result.status === 'preview'
            ? {
                selectedRowKeys: selectedKeys,
                onChange: (keys) => onSelectionChange(keys.map(String)),
                getCheckboxProps: (item) => ({ disabled: item.change === 'unchanged' }),
              }
            : undefined
        }
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
