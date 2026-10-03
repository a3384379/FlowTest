import { Alert, Button, Descriptions, Empty, Space, Spin, Table, Tabs, Tag, Typography } from 'antd'
import { useId, useState } from 'react'
import AssertionEvidence from '../evidence/AssertionEvidence'
import ResponseCodeReader from './ResponseCodeReader'
import { downloadApiResponse } from './api-service'

import { apiErrorMessage, type Execution, type ExecutionDetail } from '../../lib/api'

type Props = {
  result: ExecutionDetail | null
  history: Execution[]
  historyLoading?: boolean
  historyError?: unknown
  onRetryHistory?: () => void
  page?: number
  total?: number
  onPageChange?: (page: number) => void
  onSelectExecution?: (id: string | null) => void
  viewingHistory?: boolean
  detailLoading?: boolean
  detailError?: unknown
  onRetryDetail?: () => void
}

export default function ExecutionResultPanel(props: Props) {
  const { result, viewingHistory } = props
  const tabsId = useId()
  const [activeKey, setActiveKey] = useState('response')
  if (props.detailLoading) return <Spin description="正在读取冻结执行详情" />
  if (props.detailError)
    return (
      <LoadError
        error={props.detailError}
        onRetry={props.onRetryDetail}
        onReturn={() => props.onSelectExecution?.(null)}
      />
    )
  return (
    <>
      {viewingHistory && result && (
        <Alert
          type="info"
          title="正在查看历史执行的冻结请求与响应"
          description={`执行 ${result.execution.id} · ${formatTime(result.execution.started_at)} · 接口版本 ${result.execution.api_version_id}；当前编辑器继续保留草稿。`}
          action={<Button onClick={() => props.onSelectExecution?.(null)}>返回当前响应</Button>}
        />
      )}
      <Tabs
        id={tabsId}
        activeKey={activeKey}
        onChange={setActiveKey}
        items={[
          { key: 'response', label: '响应结果', children: <ResponseView result={result} /> },
          {
            key: 'headers',
            label: '响应头',
            children: result ? (
              <ResponseCodeReader
                key={result.execution.id}
                title="响应头"
                value={result.execution.response_headers}
              />
            ) : (
              <Empty description="未提供响应头" />
            ),
          },
          {
            key: 'request',
            label: '实际请求',
            children: result ? (
              <>
                <Typography.Text strong>
                  {result.execution.request_method} {result.execution.request_url}
                </Typography.Text>
                <ResponseCodeReader
                  key={result.execution.id}
                  title="实际请求记录"
                  value={{
                    headers: result.execution.request_headers,
                    body: result.execution.request_body,
                    target_snapshot: result.execution.target_snapshot,
                  }}
                />
              </>
            ) : (
              <Empty description="未提供请求记录" />
            ),
          },
          {
            key: 'assertions',
            label: `断言${result ? `（${result.assertions.length}）` : ''}`,
            children: <AssertionsView result={result} />,
          },
          {
            key: 'history',
            label: '执行历史',
            children: (
              <HistoryView
                {...props}
                onSelectExecution={(id) => {
                  props.onSelectExecution?.(id)
                  setActiveKey('response')
                }}
              />
            ),
          },
        ]}
      />
    </>
  )
}

function ResponseView({ result }: { result: ExecutionDetail | null }) {
  if (!result) return <Empty description="执行接口后查看响应" />
  const execution = result.execution
  return (
    <>
      {execution.error_message && <Alert type="error" showIcon title={execution.error_message} />}
      <Descriptions size="small" column={3} className="response-summary">
        <Descriptions.Item label="状态码">{execution.response_status ?? '—'}</Descriptions.Item>
        <Descriptions.Item label="响应时间">
          {execution.elapsed_ms === null ? '—' : `${execution.elapsed_ms.toFixed(1)} ms`}
        </Descriptions.Item>
        <Descriptions.Item label="结果">
          <ExecutionStatus status={execution.status} />
        </Descriptions.Item>
      </Descriptions>
      <div className="response-body-layout">
        <div>
          <Typography.Text strong>响应 Body</Typography.Text>
          {execution.response_artifact_id && (
            <ResponseFile key={execution.id} execution={execution} />
          )}
          <ResponseCodeReader key={execution.id} title="响应内容" value={execution.response_body} />
        </div>
        <aside className="response-evidence-sidebar">
          <Typography.Paragraph strong>响应断言</Typography.Paragraph>
          <AssertionsView result={result} />
        </aside>
      </div>
    </>
  )
}

function AssertionsView({ result }: { result: ExecutionDetail | null }) {
  if (!result) return <Empty description="暂无断言结果" />
  return (
    <AssertionEvidence
      items={result.assertions.map((item) => ({
        ...item,
        name: item.target ? `${item.kind} · ${item.target}` : item.kind,
      }))}
    />
  )
}

function HistoryView(props: Props) {
  return (
    <>
      <Typography.Paragraph type="secondary">
        当前接口资产的执行记录，包含所有版本；选择记录查看当时捕获的请求、响应和断言。
      </Typography.Paragraph>
      {props.historyError && (
        <LoadError error={props.historyError} onRetry={props.onRetryHistory} />
      )}
      <Table
        rowKey="id"
        size="small"
        loading={props.historyLoading}
        dataSource={props.history}
        pagination={
          props.onPageChange
            ? {
                current: props.page,
                pageSize: 20,
                total: props.total,
                showSizeChanger: false,
                onChange: props.onPageChange,
                showTotal: (total) => `共 ${total} 次执行`,
              }
            : undefined
        }
        locale={{ emptyText: '暂无执行历史' }}
        columns={[
          { title: '时间', dataIndex: 'started_at', render: formatTime },
          { title: '方法', dataIndex: 'request_method', width: 90 },
          { title: 'URL', dataIndex: 'request_url', ellipsis: true },
          { title: '状态码', dataIndex: 'response_status', width: 90 },
          {
            title: '结果',
            dataIndex: 'status',
            width: 90,
            render: (status: Execution['status']) => <ExecutionStatus status={status} />,
          },
          {
            title: '详情',
            key: 'detail',
            width: 100,
            render: (_, item: Execution) => (
              <Button
                type="link"
                onClick={() => props.onSelectExecution?.(item.id)}
                disabled={!props.onSelectExecution}
                aria-label={`查看执行 ${item.id}`}
              >
                查看详情
              </Button>
            ),
          },
        ]}
      />
    </>
  )
}

function LoadError({
  error,
  onRetry,
  onReturn,
}: {
  error: unknown
  onRetry?: () => void
  onReturn?: () => void
}) {
  return (
    <Alert
      type="error"
      title={apiErrorMessage(error)}
      action={
        <Space>
          {onRetry && <Button onClick={onRetry}>重试</Button>}
          {onReturn && <Button onClick={onReturn}>返回当前响应</Button>}
        </Space>
      }
    />
  )
}

function ResponseFile({ execution }: { execution: Execution }) {
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  async function download() {
    setLoading(true)
    setError(null)
    try {
      await downloadApiResponse(execution.project_id, execution)
    } catch (cause) {
      setError(apiErrorMessage(cause))
    } finally {
      setLoading(false)
    }
  }
  return (
    <>
      <Alert
        type="info"
        title={`大型响应已外置${execution.response_size_bytes == null ? '' : `（${execution.response_size_bytes} 字节）`}；下方显示已捕获的预览。`}
        action={
          <Button loading={loading} onClick={() => void download()}>
            下载原始响应体
          </Button>
        }
      />
      {error && <Alert type="error" title={error} />}
    </>
  )
}

function ExecutionStatus({ status }: { status: Execution['status'] }) {
  const passed = status === 'passed'
  const labels: Record<Execution['status'], string> = {
    passed: '通过',
    running: '运行中',
    failed: '失败',
    error: '执行错误',
  }
  return (
    <Tag color={passed ? 'success' : status === 'running' ? 'processing' : 'error'}>
      {labels[status]}
    </Tag>
  )
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value))
}
