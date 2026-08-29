import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'

import { listRequestServices } from '../service-targets/service-target-service'
import { apiErrorMessage, type ApiDefinition, type FlowSpecDocument } from '../../lib/api'
import {
  applyFlowSpec,
  exportFlowSpec,
  importFlowSpec,
  reviewFlowSpec,
  validateFlowSpec,
} from './flow-spec-service'

type FlowSpecReviewDialogProps = {
  open: boolean
  projectId: string
  workflowId?: string
  apis: ApiDefinition[]
  initial?: FlowSpecReviewSeed
  onClose: () => void
}

export type FlowSpecReviewSeed = {
  proposalId: string
  targetWorkflowId: string | null
  spec: FlowSpecDocument
  serviceMappings: Record<string, string>
  operationMappings: Record<string, string>
  operationVersionMappings: Record<string, number>
}

export default function FlowSpecReviewDialog(props: FlowSpecReviewDialogProps) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [rawSpec, setRawSpec] = useState(() => initialSpec(props.initial))
  const [validation, setValidation] = useState<Awaited<ReturnType<typeof validateFlowSpec>> | null>(
    null,
  )
  const [proposal, setProposal] = useState<Awaited<ReturnType<typeof importFlowSpec>> | null>(null)
  const [serviceMappings, setServiceMappings] = useState<Record<string, string>>(
    () => props.initial?.serviceMappings ?? {},
  )
  const [operationMappings, setOperationMappings] = useState<Record<string, string>>(
    () => props.initial?.operationMappings ?? {},
  )
  const [operationVersionMappings, setOperationVersionMappings] = useState<Record<string, number>>(
    () => props.initial?.operationVersionMappings ?? {},
  )
  const [busy, setBusy] = useState(false)
  const services = useQuery({
    queryKey: ['flow-spec-target-services', props.projectId],
    queryFn: () => listRequestServices(props.projectId),
    enabled: props.open,
  })
  const spec = safeFlowSpec(rawSpec)

  async function exportCurrent(): Promise<void> {
    const workflowId = props.workflowId
    if (!workflowId) return
    await act(async () => {
      const exported = await exportFlowSpec(props.projectId, workflowId)
      setRawSpec(JSON.stringify(exported.spec, null, 2))
      setValidation({
        fingerprint: exported.fingerprint,
        spec: exported.spec,
        validation: exported.validation,
        compatibility: exported.compatibility,
      })
      setProposal(null)
      setServiceMappings({})
      setOperationMappings({})
      setOperationVersionMappings({})
    }, '当前草稿已导出')
  }

  async function validate(): Promise<void> {
    const candidate = requiredSpec(spec)
    await act(async () => {
      setValidation(await validateFlowSpec(props.projectId, candidate))
      setProposal(null)
    }, 'FlowSpec 校验完成')
  }

  async function createDraft(): Promise<void> {
    const candidate = requiredSpec(spec)
    await act(async () => {
      setProposal(
        await importFlowSpec(
          props.projectId,
          candidate,
          props.workflowId,
          'ui://flow-spec-review',
          {
            service_mappings: serviceMappings,
            operation_mappings: operationMappings,
            operation_version_mappings: operationVersionMappings,
          },
        ),
      )
    }, 'FlowSpec ChangeSet Draft 已创建')
  }

  async function review(accept: boolean): Promise<void> {
    if (!proposal) return
    await act(
      async () => {
        setProposal(
          await reviewFlowSpec(
            props.projectId,
            proposal.id,
            accept,
            '前端 FlowSpec Mapping 人工审核',
          ),
        )
      },
      accept ? 'FlowSpec Draft 已接受' : 'FlowSpec Draft 已拒绝',
    )
  }

  async function apply(): Promise<void> {
    if (!proposal) return
    await act(async () => {
      await applyFlowSpec(props.projectId, proposal.id)
      await queryClient.invalidateQueries({ queryKey: ['workflows', props.projectId] })
      setProposal({ ...proposal, applied_at: new Date().toISOString() })
    }, 'FlowSpec 已应用到当前 Workflow 草稿')
  }

  async function act(operation: () => Promise<void>, success: string): Promise<void> {
    setBusy(true)
    try {
      await operation()
      void message.success(success)
    } catch (error) {
      void message.error(apiErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title="FlowSpec 导入、Mapping 与 Review"
      open={props.open}
      width={1040}
      footer={null}
      destroyOnHidden
      onCancel={props.onClose}
    >
      <Space orientation="vertical" size={16} style={{ width: '100%' }}>
        <Alert
          showIcon
          type="info"
          title="跨项目导入按 canonical contract fingerprint 校验版本：pinned 恢复显式 api_version，current 保持跟随目标 API 当前版本。"
          description={
            props.initial
              ? '已载入 MCP Proposal 快照；安全编辑会创建新的待审核 ChangeSet，不会原地修改 MCP Proposal。'
              : undefined
          }
        />
        <Space wrap>
          <Button disabled={!props.workflowId} loading={busy} onClick={() => void exportCurrent()}>
            导出当前草稿
          </Button>
          <Button disabled={!spec} loading={busy} onClick={() => void validate()}>
            校验与兼容性检查
          </Button>
          <Button
            type="primary"
            disabled={!spec || !mappingsComplete(spec, serviceMappings, operationMappings)}
            loading={busy}
            onClick={() => void createDraft()}
          >
            创建 ChangeSet Draft
          </Button>
        </Space>
        <Input.TextArea
          aria-label="FlowSpec JSON"
          rows={12}
          value={rawSpec}
          placeholder="粘贴 FlowSpec JSON，或先导出当前草稿"
          onChange={(event) => {
            setRawSpec(event.target.value)
            setValidation(null)
            setProposal(null)
          }}
        />
        {rawSpec && !spec ? <Alert type="error" showIcon title="FlowSpec JSON 无法解析" /> : null}
        {spec ? (
          <MappingReview
            spec={spec}
            services={services.data ?? []}
            apis={props.apis}
            serviceMappings={serviceMappings}
            operationMappings={operationMappings}
            operationVersionMappings={operationVersionMappings}
            onServiceMapping={(ref, id) =>
              setServiceMappings((current) => ({ ...current, [ref]: id }))
            }
            onOperationMapping={(ref, id) =>
              setOperationMappings((current) => ({ ...current, [ref]: id }))
            }
            onOperationVersionMapping={(ref, version) =>
              setOperationVersionMappings((current) => ({ ...current, [ref]: version }))
            }
          />
        ) : null}
        {validation ? <ValidationReview result={validation} /> : null}
        {proposal ? (
          <ProposalReview proposal={proposal} busy={busy} onReview={review} onApply={apply} />
        ) : null}
      </Space>
    </Modal>
  )
}

function MappingReview({
  spec,
  services,
  apis,
  serviceMappings,
  operationMappings,
  operationVersionMappings,
  onServiceMapping,
  onOperationMapping,
  onOperationVersionMapping,
}: {
  spec: FlowSpecDocument
  services: Array<{ id: string; service_key: string; name: string; enabled: boolean }>
  apis: ApiDefinition[]
  serviceMappings: Record<string, string>
  operationMappings: Record<string, string>
  operationVersionMappings: Record<string, number>
  onServiceMapping: (ref: string, id: string) => void
  onOperationMapping: (ref: string, id: string) => void
  onOperationVersionMapping: (ref: string, version: number) => void
}) {
  return (
    <Card title="Portable Resource Mapping Review" size="small">
      {!spec.services.length && !spec.operations.length ? (
        <Typography.Text type="secondary">该 FlowSpec 不含可移植资源引用。</Typography.Text>
      ) : null}
      <Form layout="vertical">
        {spec.services.map((source) => (
          <Form.Item key={source.ref} label={`Service ${source.ref} · ${source.name}`} required>
            <Select
              aria-label={`Service Mapping ${source.ref}`}
              value={serviceMappings[source.ref]}
              options={services.map((target) => ({
                value: target.id,
                label: `${target.name} · ${target.service_key}`,
                disabled: !target.enabled,
              }))}
              onChange={(value) => onServiceMapping(source.ref, value)}
            />
          </Form.Item>
        ))}
        {spec.operations.map((source) => (
          <Form.Item
            key={source.ref}
            label={`Operation ${source.ref} · ${source.method} ${source.path} · Source v${source.source_version ?? source.api_version ?? 'unversioned'}`}
            required
          >
            <Space orientation="vertical" style={{ width: '100%' }}>
              <Descriptions size="small" bordered column={2}>
                <Descriptions.Item label="Version Strategy">
                  {source.version_strategy ?? 'legacy pinned'}
                </Descriptions.Item>
                <Descriptions.Item label="Contract Fingerprint">
                  <Typography.Text code>{source.contract_fingerprint ?? 'missing'}</Typography.Text>
                </Descriptions.Item>
              </Descriptions>
              <Select
                aria-label={`Operation Mapping ${source.ref}`}
                value={operationMappings[source.ref]}
                options={apis.map((target) => ({
                  value: target.id,
                  label: `${target.name} · v${target.current_version}`,
                  disabled: !target.is_active,
                }))}
                onChange={(value) => onOperationMapping(source.ref, value)}
              />
              {source.version_strategy === 'pinned' ? (
                <InputNumber
                  aria-label={`Operation Version Mapping ${source.ref}`}
                  min={1}
                  precision={0}
                  placeholder="可选：显式目标版本；留空则按 Contract Fingerprint 匹配"
                  style={{ width: '100%' }}
                  value={operationVersionMappings[source.ref]}
                  onChange={(value) => {
                    if (typeof value === 'number') onOperationVersionMapping(source.ref, value)
                  }}
                />
              ) : null}
            </Space>
          </Form.Item>
        ))}
      </Form>
    </Card>
  )
}

function ValidationReview({ result }: { result: Awaited<ReturnType<typeof validateFlowSpec>> }) {
  const issues = [...result.validation.issues, ...result.compatibility.blockers]
  return (
    <Card title="Validation / Compatibility" size="small">
      <Descriptions size="small" column={3} bordered>
        <Descriptions.Item label="Fingerprint">{result.fingerprint}</Descriptions.Item>
        <Descriptions.Item label="Semantic">
          <Tag color={result.validation.valid ? 'green' : 'red'}>
            {result.validation.valid ? 'valid' : 'invalid'}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="Compatibility">
          <Tag color={result.compatibility.compatible ? 'green' : 'red'}>
            {result.compatibility.compatible ? 'compatible' : 'blocked'}
          </Tag>
        </Descriptions.Item>
      </Descriptions>
      {issues.map((issue) => (
        <Alert
          key={`${issue.code}:${issue.path}`}
          type="error"
          title={issue.code}
          description={`${issue.path}: ${issue.message}`}
        />
      ))}
    </Card>
  )
}

function ProposalReview({
  proposal,
  busy,
  onReview,
  onApply,
}: {
  proposal: Awaited<ReturnType<typeof importFlowSpec>>
  busy: boolean
  onReview: (accept: boolean) => Promise<void>
  onApply: () => Promise<void>
}) {
  return (
    <Card title="ChangeSet Review" size="small">
      <Space orientation="vertical" style={{ width: '100%' }}>
        <Descriptions size="small" bordered column={2}>
          <Descriptions.Item label="Status">{proposal.status}</Descriptions.Item>
          <Descriptions.Item label="Review">{proposal.review_status}</Descriptions.Item>
        </Descriptions>
        <Table
          rowKey="path"
          size="small"
          pagination={false}
          dataSource={proposal.diff}
          columns={[
            { title: 'Path', dataIndex: 'path' },
            { title: 'Before', dataIndex: 'before', render: (value) => JSON.stringify(value) },
            { title: 'After', dataIndex: 'after', render: (value) => JSON.stringify(value) },
          ]}
        />
        <Space>
          {proposal.review_status === 'pending' ? (
            <>
              <Button type="primary" loading={busy} onClick={() => void onReview(true)}>
                接受 Mapping 与 Diff
              </Button>
              <Button danger loading={busy} onClick={() => void onReview(false)}>
                拒绝
              </Button>
            </>
          ) : null}
          {proposal.review_status === 'accepted' && !proposal.applied_at ? (
            <Button type="primary" loading={busy} onClick={() => void onApply()}>
              应用到 Workflow 草稿
            </Button>
          ) : null}
          {proposal.applied_at ? <Tag color="green">已应用</Tag> : null}
        </Space>
      </Space>
    </Card>
  )
}

function safeFlowSpec(raw: string): FlowSpecDocument | null {
  if (!raw.trim()) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    return typeof parsed === 'object' && parsed !== null ? (parsed as FlowSpecDocument) : null
  } catch {
    return null
  }
}

function initialSpec(seed: FlowSpecReviewSeed | undefined): string {
  return seed ? JSON.stringify(seed.spec, null, 2) : ''
}

function requiredSpec(spec: FlowSpecDocument | null): FlowSpecDocument {
  if (!spec) throw new Error('FlowSpec JSON 无法解析')
  return spec
}

function mappingsComplete(
  spec: FlowSpecDocument,
  serviceMappings: Record<string, string>,
  operationMappings: Record<string, string>,
): boolean {
  return (
    spec.services.every((service) => Boolean(serviceMappings[service.ref])) &&
    spec.operations.every((operation) => Boolean(operationMappings[operation.ref]))
  )
}
