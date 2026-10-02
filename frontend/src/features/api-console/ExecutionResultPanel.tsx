import { Alert, Descriptions, Empty, Table, Tabs, Tag, Typography } from 'antd'
import { useId } from 'react'
import AssertionEvidence from '../evidence/AssertionEvidence'

import type { Execution, ExecutionDetail } from '../../lib/api'

type Props = {
  result: ExecutionDetail | null
  history: Execution[]
}

export default function ExecutionResultPanel({ result, history }: Props) {
  const tabsId = useId()
  return (
    <Tabs
      id={tabsId}
      items={[
        { key: 'response', label: '响应结果', children: <ResponseView result={result} /> },
        {
          key: 'headers',
          label: '响应头',
          children: result ? (
            <pre className="response-code">{formatJson(result.execution.response_headers)}</pre>
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
              <pre className="response-code">
                {formatJson({
                  headers: result.execution.request_headers,
                  body: result.execution.request_body,
                  target_snapshot: result.execution.target_snapshot,
                })}
              </pre>
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
      <div className="response-body-layout">
        <div>
          <Typography.Text strong>响应 Body</Typography.Text>
          <pre className="response-code">{formatJson(execution.response_body)}</pre>
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

function formatJson(value: unknown) {
  if (value === undefined) return '未提供'
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
