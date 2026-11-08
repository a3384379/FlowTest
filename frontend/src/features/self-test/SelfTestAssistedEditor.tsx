import { selfTestCommandConfig } from './self-test-command-config'
import { useState } from 'react'
import { Alert, Button, Checkbox, Drawer, Input, Space, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import { apiClient, apiErrorWithTrace } from '../../lib/api'
import { useSelfTestIdentity } from './self-test-query-keys'
import { useSelfTestCommand } from './use-self-test-command'
import { selfTestProposalPath, selfTestReferenceWithContext } from './self-test-navigation'
import type { MCPChangeSetEnvelope } from '../mcp/mcp-change-set-service'
import type { TestDesignDocument } from '../test-engineering/test-engineering-service'
import type { TestCaseDraftInput } from '../test-assets/test-asset-service'

type RevisionDocument = {
  design: TestDesignDocument
  test_cases: Array<{
    name: string
    description: string
    tags: string[]
    definition: TestCaseDraftInput['definition']
  }>
}
function revisionDocument(text: string): RevisionDocument {
  const value: unknown = JSON.parse(text)
  if (
    !value ||
    typeof value !== 'object' ||
    !('design' in value) ||
    !('test_cases' in value) ||
    !Array.isArray(value.test_cases) ||
    !value.test_cases.length ||
    value.test_cases.length > 50 ||
    Object.keys(value).some((key) => !['design', 'test_cases'].includes(key))
  )
    throw new Error('请输入包含 design 与 1–50 项 test_cases 的修订文档。完整内容由服务端校验。')
  return value as RevisionDocument
}
export default function SelfTestAssistedEditor({
  projectId,
  batchId,
  beforeBatchId,
  allowed,
}: {
  projectId: string
  batchId: string
  beforeBatchId: string
  allowed: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Alert
        type="warning"
        title="本批次是辅助修订任务，原模型证据与首次结果保留"
        description={`原批次：${beforeBatchId}。Workflow 使用既有 FlowSpec 提案、审核与发布；Case 从此入口提交人工提案。部署宿主仍需读取新的授权和发布回执，网页不会调用模型。`}
      />
      <Button disabled={!allowed} onClick={() => setOpen(true)}>
        提交人工 Case 修订提案
      </Button>
      {open && (
        <AssistedEditorDrawer
          projectId={projectId}
          batchId={batchId}
          beforeBatchId={beforeBatchId}
          allowed={allowed}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  )
}
function AssistedEditorDrawer({
  projectId,
  batchId,
  beforeBatchId,
  allowed,
  onClose,
}: {
  projectId: string
  batchId: string
  beforeBatchId: string
  allowed: boolean
  onClose: () => void
}) {
  const identity = useSelfTestIdentity(projectId)
  const [params] = useSearchParams()
  const [reason, setReason] = useState('')
  const [document, setDocument] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [failure, setFailure] = useState<unknown>(null)
  const [proposalId, setProposalId] = useState<string>()
  const command = useSelfTestCommand({
    identity,
    selectionKey: `assisted:${batchId}`,
    allowed: allowed && confirmed,
    send: async (input: RevisionDocument & { reason: string }, key: string) => {
      const response = await apiClient.post<MCPChangeSetEnvelope>(
        `/projects/${projectId}/self-tests/runs/${batchId}/assisted-case-proposals`,
        {
          project_id: projectId,
          idempotency_key: key,
          dry_run: false,
          title: `人工辅助修订：${input.reason}`,
          source_ref: `mcp://selftest/assisted/${batchId}`,
          confidence: 1,
          risk_level: 'medium',
          design: input.design,
          test_cases: input.test_cases.map((item) => ({
            ...item,
            description: `${item.description ?? ''}\n修订原因：${input.reason}`,
          })),
        },
        selfTestCommandConfig(key),
      )
      if (
        response.data.data.project_id !== projectId ||
        !/^[0-9a-f-]{36}$/i.test(response.data.data.id)
      )
        throw new Error('修订提案回执范围无效。')
      return response.data.data.id
    },
  })
  async function submit() {
    setFailure(null)
    try {
      const result = await command.execute({ ...revisionDocument(document), reason: reason.trim() })
      if (result) setProposalId(result)
    } catch (error) {
      setFailure(error)
    }
  }
  return (
    <Drawer open title="人工 Case 修订提案" onClose={onClose} size={850}>
      <Typography.Paragraph>
        修订前批次：{beforeBatchId}。输入保留原 Design 与必要 Oracle 的文档，以及指向新 Workflow
        发布版本的 Case 定义。真实差异、编辑者与审核者在物化时由服务端核对。
      </Typography.Paragraph>
      <label>
        修订原因
        <Input
          aria-label="修订原因"
          maxLength={120}
          value={reason}
          onChange={(event) => {
            setReason(event.target.value)
            setConfirmed(false)
          }}
        />
      </label>
      <label>
        修订文档（JSON）
        <Input.TextArea
          aria-label="修订文档"
          rows={18}
          maxLength={500000}
          value={document}
          placeholder={
            '{"design": {…原设计…}, "test_cases": [{"name":"…", "description":"…", "tags":[], "definition":{…}}]}'
          }
          onChange={(event) => {
            setDocument(event.target.value)
            setConfirmed(false)
          }}
        />
      </label>
      <Checkbox checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)}>
        我确认保留必要断言并提交新的人工审核提案
      </Checkbox>
      <Space>
        <Button
          disabled={!allowed || !confirmed || !reason.trim() || !document.trim() || !!proposalId}
          loading={command.pending}
          onClick={() => void submit()}
        >
          创建人工提案
        </Button>
        {proposalId && (
          <Link
            to={selfTestProposalPath(
              projectId,
              'controlled_write',
              proposalId,
              selfTestReferenceWithContext({ batchId }, params),
            )}
          >
            进入人工审核与发布
          </Link>
        )}
      </Space>
      {Boolean(failure || command.error) && (
        <Alert type="error" title={apiErrorWithTrace(failure || command.error)} />
      )}
    </Drawer>
  )
}
