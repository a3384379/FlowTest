import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Collapse, Descriptions, Drawer, Space, Table, Typography } from 'antd'
import { useState } from 'react'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import type { ContractRun } from '../../lib/api'
import {
  getDeploymentCheck,
  getPactContract,
  getProviderVerification,
  type DeploymentCheck,
  type PactContractDetail,
  type ProviderVerificationDetail,
} from './contract-hub-service'
import { getContractRun } from './contract-service'

export type ContractEvidenceSelection = {
  kind: 'run' | 'pact' | 'verification' | 'check'
  id: string
}
type Evidence =
  | { kind: 'run'; record: ContractRun }
  | { kind: 'pact'; record: PactContractDetail }
  | { kind: 'verification'; record: ProviderVerificationDetail }
  | { kind: 'check'; record: DeploymentCheck }

export default function ContractEvidenceViewer({
  projectId,
  selection,
  onClose,
}: {
  projectId: string | null
  selection: ContractEvidenceSelection | null
  onClose: () => void
}) {
  if (!projectId || !selection) return null
  return (
    <ContractEvidenceDrawer
      key={`${selection.kind}:${selection.id}`}
      projectId={projectId}
      selection={selection}
      onClose={onClose}
    />
  )
}

function ContractEvidenceDrawer({
  projectId,
  selection,
  onClose,
}: {
  projectId: string
  selection: ContractEvidenceSelection
  onClose: () => void
}) {
  const [history, setHistory] = useState([selection])
  const current = history[history.length - 1]
  function onSelect(next: ContractEvidenceSelection) {
    setHistory((items) => {
      const found = items.findIndex((item) => item.kind === next.kind && item.id === next.id)
      return found < 0 ? [...items, next] : items.slice(0, found + 1)
    })
  }
  const query = useQuery({
    queryKey: ['contract-frozen-evidence', projectId, current.kind, current.id],
    queryFn: () => readEvidence(projectId, current),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
  return (
    <Drawer title="契约冻结证据" open onClose={onClose} size="min(960px, 100vw)">
      {history.length > 1 && (
        <Button onClick={() => setHistory((items) => items.slice(0, -1))}>返回上级证据</Button>
      )}
      <Alert
        type="info"
        showIcon
        title="读取已保存的固定记录"
        description="此处只展示该记录及其引用的固定契约版本。不会执行提供方验证、访问 Broker 或接受生成草稿。"
      />
      <QueryFailureNotice queries={[query]} />
      {query.isPending && <Typography.Text>正在读取证据</Typography.Text>}
      {query.data && <EvidenceContent evidence={query.data} onSelect={onSelect} />}
    </Drawer>
  )
}

async function readEvidence(
  projectId: string,
  selection: ContractEvidenceSelection,
): Promise<Evidence> {
  if (selection.kind === 'run')
    return { kind: 'run', record: await getContractRun(projectId, selection.id) }
  if (selection.kind === 'pact')
    return { kind: 'pact', record: await getPactContract(projectId, selection.id) }
  if (selection.kind === 'verification')
    return { kind: 'verification', record: await getProviderVerification(projectId, selection.id) }
  return { kind: 'check', record: await getDeploymentCheck(projectId, selection.id) }
}

function EvidenceContent({
  evidence,
  onSelect,
}: {
  evidence: Evidence
  onSelect: (selection: ContractEvidenceSelection) => void
}) {
  if (evidence.kind === 'run') return <RunEvidence record={evidence.record} onSelect={onSelect} />
  if (evidence.kind === 'pact') return <PactEvidence record={evidence.record} />
  if (evidence.kind === 'verification') return <VerificationEvidence record={evidence.record} />
  return <CheckEvidence record={evidence.record} onSelect={onSelect} />
}

function RunEvidence({
  record,
  onSelect,
}: {
  record: ContractRun
  onSelect: (selection: ContractEvidenceSelection) => void
}) {
  return (
    <Space orientation="vertical" className="full-width">
      {record.status !== 'completed' && (
        <Alert type="warning" title="分析未成功，不能据此判断没有破坏性变更" />
      )}
      <Descriptions
        column={1}
        items={[
          { label: '固定分析批次', children: record.id },
          { label: '文档', children: record.source_name },
          { label: '内容 SHA-256', children: record.source_sha256 },
          { label: '分析状态', children: record.status },
          { label: '提供方版本', children: record.provider_version ?? '未绑定' },
          {
            label: '固定基线',
            children: record.baseline_run_id ? (
              <Button onClick={() => onSelect({ kind: 'run', id: record.baseline_run_id! })}>
                {record.baseline_run_id}
              </Button>
            ) : (
              '未提供'
            ),
          },
        ]}
      />
      <Typography.Title level={5}>
        破坏性变更（{record.breaking_changes.length}项）
      </Typography.Title>
      <Table
        rowKey={(item) => `${item.operation_key}:${item.code}:${item.path}`}
        pagination={false}
        size="small"
        scroll={{ x: 640 }}
        dataSource={record.breaking_changes}
        columns={[
          { title: '变更', dataIndex: 'message' },
          { title: '代码', dataIndex: 'code' },
          { title: '操作', dataIndex: 'operation_key' },
          { title: '路径', dataIndex: 'path' },
          { title: '基线值', render: (_, item) => <JsonValue value={item.before} /> },
          { title: '当前固定值', render: (_, item) => <JsonValue value={item.after} /> },
        ]}
      />
      <AdvancedJson value={record} />
    </Space>
  )
}

function PactEvidence({ record }: { record: PactContractDetail }) {
  const { contract, contract_document: document } = record
  return (
    <Space orientation="vertical" className="full-width">
      <Descriptions
        column={1}
        items={[
          { label: '固定Pact版本', children: contract.id },
          { label: 'Consumer → Provider', children: `${document.consumer} → ${document.provider}` },
          { label: '消费者版本', children: contract.consumer_version },
          { label: '内容 SHA-256', children: contract.content_sha256 },
        ]}
      />
      {document.interactions.map((item, index) => (
        <Card size="small" key={index} title={`Interaction ${index + 1} · ${item.description}`}>
          <Typography.Text>
            {item.request.method} {item.request.path}
          </Typography.Text>
          <Typography.Title level={5}>固定预期响应</Typography.Title>
          <Typography.Text>状态码：{item.response.status}</Typography.Text>
          <JsonValue value={item.response} />
        </Card>
      ))}
      <AdvancedJson value={record} />
    </Space>
  )
}

function VerificationEvidence({ record }: { record: ProviderVerificationDetail }) {
  const { verification, pact } = record
  return (
    <Space orientation="vertical" className="full-width">
      <Descriptions
        column={1}
        items={[
          { label: '固定验证记录', children: verification.id },
          { label: '固定Pact版本', children: verification.pact_contract_version_id },
          { label: '提供方版本', children: verification.provider_version },
          { label: '验证结果', children: verification.status },
          { label: '验证时间', children: verification.created_at },
        ]}
      />
      <Alert
        type="warning"
        showIcon
        title="实际响应未采集"
        description="该历史验证仅保存 Interaction 状态和不匹配代码，没有保存实际 HTTP 状态码、响应头或正文，无法还原实际值。"
      />
      {verification.results.map((result) => (
        <Card
          size="small"
          key={result.interaction_index}
          title={`Interaction ${result.interaction_index + 1} · ${result.description}`}
        >
          <Typography.Text>
            {result.status} · {result.mismatch_codes.join('、') || '无不匹配代码'}
          </Typography.Text>
          <Typography.Title level={5}>该次验证的固定预期</Typography.Title>
          <ExpectedInteraction pact={pact} index={result.interaction_index} />
          <Typography.Text>实际值：未提供</Typography.Text>
        </Card>
      ))}
      <AdvancedJson value={record} />
    </Space>
  )
}

function ExpectedInteraction({ pact, index }: { pact: PactContractDetail; index: number }) {
  const expected = pact.contract_document.interactions[index]
  return expected ? (
    <JsonValue value={expected.response} />
  ) : (
    <Alert type="warning" title="固定Interaction预期未提供" />
  )
}

function CheckEvidence({
  record,
  onSelect,
}: {
  record: DeploymentCheck
  onSelect: (selection: ContractEvidenceSelection) => void
}) {
  return (
    <Space orientation="vertical" className="full-width">
      <Descriptions
        column={1}
        items={[
          { label: '固定发布判断', children: record.id },
          { label: '提供方', children: textField(record.evidence, 'provider_name') ?? '未提供' },
          { label: '提供方版本', children: record.provider_version },
          { label: '判断', children: record.decision },
          { label: '判断时间', children: record.created_at },
        ]}
      />
      <BlockerList title="阻断证据" value={record.evidence.blockers} onSelect={onSelect} />
      <BlockerList title="待补证据" value={record.evidence.pending} onSelect={onSelect} />
      <AdvancedJson value={record} />
    </Space>
  )
}

function BlockerList({
  title,
  value,
  onSelect,
}: {
  title: string
  value: unknown
  onSelect: (selection: ContractEvidenceSelection) => void
}) {
  if (!Array.isArray(value)) return <Alert type="warning" title={`${title}未提供`} />
  return (
    <Space orientation="vertical" className="full-width">
      <Typography.Title level={5}>
        {title}（{value.length}项）
      </Typography.Title>
      {value.map((item: unknown, index: number) => (
        <Card
          size="small"
          key={index}
          title={`${index + 1}. ${textField(item, 'code') ?? '证据代码未提供'}`}
        >
          <EvidenceReference
            value={item}
            field="verification_id"
            kind="verification"
            label="查看固定验证"
            onSelect={onSelect}
          />
          <EvidenceReference
            value={item}
            field="pact_contract_version_id"
            kind="pact"
            label="查看固定Pact"
            onSelect={onSelect}
          />
          <EvidenceReference
            value={item}
            field="contract_run_id"
            kind="run"
            label="查看固定OpenAPI分析"
            onSelect={onSelect}
          />
          <JsonValue value={item} />
        </Card>
      ))}
    </Space>
  )
}

function EvidenceReference({
  value,
  field,
  kind,
  label,
  onSelect,
}: {
  value: unknown
  field: string
  kind: ContractEvidenceSelection['kind']
  label: string
  onSelect: (selection: ContractEvidenceSelection) => void
}) {
  const id = textField(value, field)
  return id ? (
    <Button size="small" onClick={() => onSelect({ kind, id })}>
      {label}
    </Button>
  ) : null
}

function textField(value: unknown, field: string): string | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const item = (value as Record<string, unknown>)[field]
  return typeof item === 'string' ? item : null
}

function JsonValue({ value }: { value: unknown }) {
  const text = value === undefined ? '未提供' : JSON.stringify(value, null, 2)
  return (
    <pre
      style={{ maxHeight: 280, overflow: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}
    >
      {text}
    </pre>
  )
}

function AdvancedJson({ value }: { value: unknown }) {
  return (
    <Collapse
      items={[
        { key: 'source', label: '高级：只读证据 JSON', children: <JsonValue value={value} /> },
      ]}
    />
  )
}
