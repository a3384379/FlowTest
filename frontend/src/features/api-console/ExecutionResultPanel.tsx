import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { Alert, Descriptions, Empty, Table, Tabs, Tag, Typography } from 'antd'

import type { Execution, ExecutionDetail } from '../../lib/api'

type Props = {
  result: ExecutionDetail | null
  history: Execution[]
}

export default function ExecutionResultPanel({ result, history }: Props) {
  return (
    <Tabs
      items={[
        { key: 'response', label: '响应', children: <ResponseView result={result} /> },
        { key: 'assertions', label: '断言', children: <AssertionsView result={result} /> },
        { key: 'history', label: '执行历史', children: <HistoryView history={history} /> },
      ]}
    />
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
      <Typography.Text strong>请求目标快照</Typography.Text>
      <pre className="response-code">{formatJson(execution.target_snapshot)}</pre>
      <Typography.Text strong>响应 Body</Typography.Text>
      <pre className="response-code">{formatJson(execution.response_body)}</pre>
    </>
  )
}

function AssertionsView({ result }: { result: ExecutionDetail | null }) {
  if (!result) return <Empty description="暂无断言结果" />
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={result.assertions}
      columns={[
        {
          title: '结果',
          dataIndex: 'passed',
          render: (passed: boolean) =>
            passed ? (
              <Tag icon={<CheckCircleOutlined />} color="success">
                通过
              </Tag>
            ) : (
              <Tag icon={<CloseCircleOutlined />} color="error">
                失败
              </Tag>
            ),
        },
        { title: '类型', dataIndex: 'kind' },
        { title: '目标', dataIndex: 'target', render: (value: string | null) => value ?? '—' },
        { title: '说明', dataIndex: 'message' },
      ]}
    />
  )
}

function HistoryView({ history }: { history: Execution[] }) {
  return (
    <Table
      rowKey="id"
      size="small"
      dataSource={history}
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
      ]}
    />
  )
}

function ExecutionStatus({ status }: { status: Execution['status'] }) {
  const passed = status === 'passed'
  return <Tag color={passed ? 'green' : status === 'running' ? 'blue' : 'red'}>{status}</Tag>
}

function formatJson(value: unknown) {
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2) ?? ''
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value))
}
