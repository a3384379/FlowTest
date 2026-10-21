import { Alert, Button, Collapse, Descriptions, Space, Typography } from 'antd'
import { useState } from 'react'

import { confidenceLabel } from '../test-engineering/design-confidence'
import type { MCPChangeSetEnvelope } from './mcp-change-set-service'

export default function MCPGovernanceSummary({ envelope }: { envelope: MCPChangeSetEnvelope }) {
  const data = envelope.data
  const governance = data.governance
  return (
    <Space orientation="vertical" className="full-width">
      <Descriptions
        column={2}
        items={[
          { label: '风险等级', children: governance.risk_level },
          { label: '治理置信度', children: confidenceLabel(governance.confidence) },
          { label: '要求人工审核', children: booleanLabel(governance.requires_review) },
          { label: '要求人工审批', children: booleanLabel(governance.manual_approval_required) },
          {
            label: '风险及审核原因',
            span: 2,
            children: governance.reason_codes.length ? (
              <ul>
                {governance.reason_codes.map((reason, index) => (
                  <li key={index}>
                    {reasonLabel(reason)}（{reason}）
                  </li>
                ))}
              </ul>
            ) : (
              '未提供额外原因'
            ),
          },
          { label: '来源引用', children: data.source_ref ?? '未提供' },
          {
            label: '来源指纹',
            children: <Typography.Text copyable>{data.source_fingerprint}</Typography.Text>,
          },
        ]}
      />
      {data.approval && (
        <Descriptions
          column={2}
          items={[
            { label: '审批 ID', children: data.approval.id },
            { label: '审批决定', children: data.approval.decision },
            { label: '审批人 ID', children: data.approval.approved_by_id },
            { label: '审批时间', children: data.approval.approved_at },
          ]}
        />
      )}
      <Collapse
        key={envelope.trace_id}
        defaultActiveKey={envelope.warnings.length ? ['diagnostics'] : []}
        items={[
          {
            key: 'diagnostics',
            label: `警告与请求诊断（${envelope.warnings.length} 条警告）`,
            children: (
              <Space orientation="vertical" className="full-width">
                <Typography.Text type="secondary">
                  警告供人工核对；硬性审批、权限与修订冲突仍由服务端拒绝。
                </Typography.Text>
                {envelope.warnings.length ? (
                  envelope.warnings.map((warning, index) => (
                    <Alert key={index} type="warning" showIcon title={warning} />
                  ))
                ) : (
                  <Typography.Text>本次读取没有附加警告。</Typography.Text>
                )}
                <TraceIdentity traceId={envelope.trace_id} />
              </Space>
            ),
          },
        ]}
      />
    </Space>
  )
}

function TraceIdentity({ traceId }: { traceId: string }) {
  const [copied, setCopied] = useState<{ traceId: string; status: string } | null>(null)
  const status = copied?.traceId === traceId ? copied.status : null
  async function copy() {
    try {
      await navigator.clipboard.writeText(traceId)
      setCopied({ traceId, status: 'Trace ID 已复制' })
    } catch {
      setCopied({ traceId, status: 'Trace ID 复制失败，请手动复制' })
    }
  }
  return (
    <Space wrap>
      <Typography.Text>
        Trace ID：<Typography.Text code>{traceId || '未提供'}</Typography.Text>
      </Typography.Text>
      <Button
        size="small"
        aria-label="复制 Trace ID"
        disabled={!traceId}
        onClick={() => void copy()}
      >
        复制 Trace ID
      </Button>
      {status && <Typography.Text role="status">{status}</Typography.Text>}
    </Space>
  )
}
function reasonLabel(value: string): string {
  if (value === 'low_confidence_assertion_review') return '低置信度预期需要人工审核'
  if (value === 'manual_approval_required') return '高风险变更需要人工审批'
  return '未映射原因，保留服务端代码供核对'
}

function booleanLabel(value: unknown): string {
  return typeof value === 'boolean' ? (value ? '是' : '否') : '未提供'
}
