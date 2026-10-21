import { AuditOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Descriptions,
  Flex,
  Space,
  Tag,
  Typography,
} from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import { useAuthStore } from '../features/auth/auth-store'
import MCPGovernanceSummary from '../features/mcp/MCPGovernanceSummary'
import MCPStructuredPreview from '../features/mcp/MCPStructuredPreview'
import MCPMaterializedResult from '../features/mcp/MCPMaterializedResult'
import ResponseCodeReader from '../features/api-console/ResponseCodeReader'
import QueryFailureNotice from '../components/QueryFailureNotice'

import {
  approveMCPChangeSet,
  getMCPChangeSet,
  reviewMCPChangeItem,
  type MCPChangeItem,
  type MCPChangeSet,
  type MCPChangeSetEnvelope,
} from '../features/mcp/mcp-change-set-service'
import ControlBlockGraphPreview from '../features/mcp/ControlBlockGraphPreview'
import ControlWorkflowGraphPreview from '../features/mcp/ControlWorkflowGraphPreview'
import { apiErrorMessage, apiErrorTraceId, type WorkflowDefinition } from '../lib/api'
import { useProjectContext } from '../features/projects/use-project-context'
import { useProjectCapabilities } from '../features/projects/use-project-capabilities'

export default function MCPChangeSetsPage() {
  const { projectId } = useProjectContext()
  const [params] = useSearchParams()
  const actor = useAuthStore((state) => `${state.user?.id}:${state.organizationId}`)
  return (
    <MCPChangeSetWorkspace key={`${projectId}:${params.get('focus')}:${actor}`} scope={actor} />
  )
}

function MCPChangeSetWorkspace({ scope }: { scope: string }) {
  const { projectId } = useProjectContext()
  const { canEdit, permissions } = useProjectCapabilities()
  const [searchParams] = useSearchParams()
  const focusId = searchParams.get('focus')
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const active = useRef(true)
  const [actionError, setActionError] = useState<unknown>(null)
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  const changeSet = useQuery({
    queryKey: ['mcp-change-set', scope, projectId, focusId],
    queryFn: async () => {
      const result = await getMCPChangeSet(required(focusId))
      if (result.data.project_id !== projectId)
        throw new Error('该变更集不属于当前项目，请核对项目和 ChangeSet ID。')
      if (result.data.id !== focusId)
        throw new Error('返回的变更集 ID 与当前定位不一致，请重新读取。')
      return result
    },
    enabled: Boolean(projectId && focusId),
  })
  const approve = useMutation({
    mutationFn: (changeSetId: string) => approveMCPChangeSet(changeSetId, '前端人工批准'),
  })
  const review = useMutation({
    mutationFn: ({
      changeSetId,
      itemId,
      decision,
      approvalId,
    }: {
      changeSetId: string
      itemId: string
      decision: 'accept' | 'reject'
      approvalId: string | null
    }) => reviewMCPChangeItem(changeSetId, itemId, decision, approvalId),
  })

  async function updateReceipt(result: MCPChangeSetEnvelope): Promise<void> {
    if (result.data.id !== focusId || result.data.project_id !== projectId)
      throw new Error('审核回执与当前变更集或项目不一致，请重新读取。')
    queryClient.setQueryData(['mcp-change-set', scope, projectId, focusId], result)
    await queryClient.invalidateQueries({ queryKey: ['mcp-change-set', scope, projectId, focusId] })
  }

  async function approveChangeSet(): Promise<void> {
    if (!editable || busy) return
    setActionError(null)
    try {
      const result = await approve.mutateAsync(required(focusId))
      if (!active.current) return
      confirmApprovalReceipt(result)
      await updateReceipt(result)
      if (active.current) void message.success('MCP 变更集已完成人工批准')
    } catch (error) {
      if (active.current) {
        setActionError(error)
        void message.error(apiErrorMessage(error))
      }
    }
  }

  async function reviewItem(itemId: string, decision: 'accept' | 'reject'): Promise<void> {
    if (!editable || busy) return
    setActionError(null)
    try {
      const result = await review.mutateAsync({
        changeSetId: required(focusId),
        itemId,
        decision,
        approvalId: approvalIdentity(data),
      })
      if (!active.current) return
      confirmReviewReceipt(result, itemId, decision)
      await updateReceipt(result)
      await Promise.all(
        materializedQueryPrefixes(result.data, itemId).map((prefix) =>
          queryClient.invalidateQueries({ queryKey: [prefix, projectId] }),
        ),
      )
      if (active.current)
        void message.success(decision === 'accept' ? '变更项已接受并物化' : '变更项已拒绝')
    } catch (error) {
      if (active.current) {
        setActionError(error)
        void message.error(apiErrorMessage(error))
      }
    }
  }

  async function readAfterFailure(): Promise<void> {
    const [nextData, nextPermission] = await Promise.all([
      changeSet.refetch(),
      permissions.refetch(),
    ])
    if (active.current && nextData.isSuccess && nextPermission.isSuccess) setActionError(null)
  }

  const data = changeSet.data?.data
  const editable = editableRead(canEdit, permissions, changeSet) && actionError === null
  const busy = approve.isPending || review.isPending
  return (
    <Flex vertical gap={16}>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>MCP 受控变更审核</Typography.Title>
          <Typography.Text type="secondary">
            按精确 ChangeSet ID 审核控制流工作流、控制块、Test Design、TestCase 与 TestPlan 更新。
          </Typography.Text>
        </div>
      </div>
      {!focusId ? (
        <Alert showIcon type="info" title="请从资源发现结果打开一个 MCP 变更集。" />
      ) : null}
      <QueryFailureNotice queries={[changeSet, permissions]} />
      <ActionFailure error={actionError} onRead={readAfterFailure} />
      <ReadStaleNotice hasData={Boolean(data)} failed={changeSet.isError} />

      <Card
        loading={changeSet.isLoading}
        title={data?.title ?? '受控变更集'}
        extra={data ? <Tag>{data.status}</Tag> : null}
      >
        {data ? (
          <MCPReviewContent
            data={data}
            envelope={changeSet.data!}
            editable={editable}
            approvePending={approve.isPending}
            reviewPending={busy}
            onApprove={approveChangeSet}
            onReview={reviewItem}
          />
        ) : null}
      </Card>
    </Flex>
  )
}

type MCPReviewActions = {
  data: MCPChangeSet
  editable: boolean
  reviewPending: boolean
  onReview: (id: string, decision: 'accept' | 'reject') => Promise<void>
}

function MCPReviewContent({
  data,
  envelope,
  editable,
  approvePending,
  reviewPending,
  onApprove,
  onReview,
}: MCPReviewActions & {
  envelope: MCPChangeSetEnvelope
  approvePending: boolean
  onApprove: () => Promise<void>
}) {
  return (
    <Flex vertical gap={12}>
      <Space wrap>
        <Tag color="blue">{data.governance.risk_level}</Tag>
        <Typography.Text code>{data.id}</Typography.Text>
      </Space>
      <MCPGovernanceSummary envelope={envelope} />
      {data.governance.manual_approval_required && data.approval?.decision !== 'approved' ? (
        <Alert
          showIcon
          type="warning"
          title="高风险变更必须先人工批准"
          description="审批尚未通过，服务端会拒绝接受并物化；警告提示不替代审批。"
          action={
            <Button
              aria-label="批准变更集"
              disabled={!editable || reviewPending || Boolean(data.approval)}
              icon={<AuditOutlined />}
              loading={approvePending}
              onClick={() => void onApprove()}
            >
              批准变更集
            </Button>
          }
        />
      ) : null}
      {data.items.map((item) => (
        <MCPChangeItemCard
          key={item.id}
          item={item}
          data={data}
          editable={editable}
          reviewPending={reviewPending}
          onReview={onReview}
        />
      ))}
    </Flex>
  )
}

function MCPChangeItemCard({
  item,
  data,
  editable,
  reviewPending,
  onReview,
}: MCPReviewActions & { item: MCPChangeItem }) {
  return (
    <Card
      key={item.id}
      size="small"
      title={
        <Space wrap>
          <Tag>{item.item_type}</Tag>
          <Typography.Text strong>{item.title}</Typography.Text>
        </Space>
      }
      extra={
        item.review_status === 'pending' ? (
          <Space>
            <Button
              aria-label="拒绝"
              disabled={!editable || reviewPending}
              onClick={() => void onReview(item.id, 'reject')}
            >
              拒绝
            </Button>
            <Button
              type="primary"
              disabled={materializationDisabled(editable, reviewPending, data)}
              onClick={() => void onReview(item.id, 'accept')}
            >
              接受并物化
            </Button>
          </Space>
        ) : (
          <Tag color={item.review_status === 'accepted' ? 'success' : 'default'}>
            {item.review_status === 'accepted' ? '已接受' : '已拒绝'}
          </Tag>
        )
      }
    >
      {item.item_type === 'workflow' ? (
        <WorkflowReviewSummary
          item={item}
          changeSetId={data.id}
          projectId={data.project_id}
          workflowId={data.workflow_id ?? item.target_resource_id ?? null}
          baseRevision={data.base_revision ?? null}
        />
      ) : null}
      <MCPStructuredPreview item={item} projectId={data.project_id} />
      <MCPMaterializedResult item={item} projectId={data.project_id} changeSetId={data.id} />
      <ItemReviewRecord item={item} />
      <Collapse
        items={[
          {
            key: 'raw',
            label: '完整提案（只读核对）',
            children: <ResponseCodeReader title="完整提案" value={item.proposed_content} />,
          },
        ]}
      />
    </Card>
  )
}

function ReadStaleNotice({ hasData, failed }: { hasData: boolean; failed: boolean }) {
  if (!hasData || !failed) return null
  return <Alert type="warning" title="读取失败，保留的审核证据可能过期；重新读取成功前不能审核" />
}

function ActionFailure({ error, onRead }: { error: unknown; onRead: () => Promise<void> }) {
  if (!error) return null
  const traceId = apiErrorTraceId(error)
  return (
    <Alert
      showIcon
      type="error"
      title="审核结果未确认"
      action={<Button onClick={() => void onRead()}>重新读取变更集</Button>}
      description={
        <Space orientation="vertical">
          <Typography.Text>{apiErrorMessage(error)}</Typography.Text>
          {traceId && <Typography.Text copyable>Trace ID: {traceId}</Typography.Text>}
        </Space>
      }
    />
  )
}

function confirmApprovalReceipt(result: MCPChangeSetEnvelope): void {
  if (result.data.approval?.decision !== 'approved' || !result.data.approval.id)
    throw new Error('服务端回执未确认审批已通过，请重新读取变更集核对。')
}

function confirmReviewReceipt(
  result: MCPChangeSetEnvelope,
  itemId: string,
  decision: 'accept' | 'reject',
): void {
  const item = result.data.items.find((candidate) => candidate.id === itemId)
  const expected = decision === 'accept' ? 'accepted' : 'rejected'
  if (!item || item.review_status !== expected)
    throw new Error('服务端回执未确认被操作项的审核状态，请重新读取变更集核对。')
  if (decision === 'accept' && !hasConfirmedMaterialization(item))
    throw new Error('服务端回执未确认匹配的物化结果，请重新读取变更集核对。')
}

function hasConfirmedMaterialization(item: MCPChangeItem): boolean {
  if (!item.materialized_resource_id) return false
  if (item.item_type === 'test_plan_update') return item.materialized_resource_type === 'test_plan'
  return (
    ['workflow', 'test_design', 'test_case'].includes(item.item_type) &&
    item.materialized_resource_type === item.item_type
  )
}

function materializedQueryPrefixes(data: MCPChangeSet, itemId: string): string[] {
  const item = data.items.find((candidate) => candidate.id === itemId)
  if (!item || item.review_status !== 'accepted') return []
  if (item.materialized_resource_type === 'workflow') return ['workflows', 'workflow']
  if (item.materialized_resource_type === 'test_case')
    return ['test-cases', 'test-case-options', 'asset-directory-counts']
  if (item.materialized_resource_type === 'test_plan')
    return ['test-plans', 'test-plan', 'asset-plans']
  return []
}

function ItemReviewRecord({ item }: { item: MCPChangeItem }) {
  return (
    <Descriptions
      column={2}
      size="small"
      items={[
        { label: '审核人 ID', children: item.reviewed_by_id ?? '未提供' },
        { label: '审核时间', children: item.reviewed_at ?? '未提供' },
        { label: '审核说明', children: item.review_note || '未提供' },
      ]}
    />
  )
}

function editableRead(
  canEdit: boolean,
  permissions: { isSuccess: boolean; isError: boolean },
  changeSet: { isSuccess: boolean; isError: boolean },
): boolean {
  return (
    canEdit &&
    permissions.isSuccess &&
    !permissions.isError &&
    changeSet.isSuccess &&
    !changeSet.isError
  )
}
function approvalIdentity(data: MCPChangeSet | undefined): string | null {
  return data?.approval?.id ?? null
}

function materializationDisabled(editable: boolean, pending: boolean, data: MCPChangeSet): boolean {
  return (
    !editable ||
    pending ||
    (data.governance.manual_approval_required && data.approval?.decision !== 'approved')
  )
}

function WorkflowReviewSummary({
  item,
  changeSetId,
  projectId,
  workflowId,
  baseRevision,
}: {
  item: MCPChangeItem
  changeSetId: string
  projectId: string
  workflowId: string | null
  baseRevision: number | null
}) {
  if (item.action === 'create') {
    return <ControlWorkflowReviewSummary item={item} projectId={projectId} />
  }
  return (
    <ControlBlockReviewSummary
      changeSetId={changeSetId}
      item={item}
      workflowId={workflowId}
      baseRevision={baseRevision}
      projectId={projectId}
    />
  )
}

function ControlWorkflowReviewSummary({
  item,
  projectId,
}: {
  item: MCPChangeItem
  projectId: string
}) {
  const content = item.proposed_content as {
    name?: string
    definition?: WorkflowDefinition
  }
  const definition = content.definition
  if (!definition) return <Alert showIcon type="error" title="提案缺少工作流定义" />
  const controls = definition.nodes.filter((node) =>
    node.capability_id?.startsWith('flow.control.'),
  )
  return (
    <Flex vertical gap={8}>
      <Alert showIcon type="info" title="人工接受后才会创建工作流草稿；不会发布或执行" />
      <Space wrap>
        <Typography.Text strong>{content.name}</Typography.Text>
        <Tag>主节点 {definition.nodes.length}</Tag>
        <Tag>内联区域 {definition.regions?.length ?? 0}</Tag>
        {controls.map((node) => (
          <Tag color="blue" key={node.id}>
            {node.capability_id}
          </Tag>
        ))}
        <ControlWorkflowGraphPreview
          definition={definition}
          projectId={projectId}
          proposalId={item.id}
        />
      </Space>
      {(definition.regions ?? []).map((region) => (
        <Typography.Text key={region.id}>
          区域 {region.role}：{region.nodes.map((node) => node.name).join(' → ') || '空区域'}
        </Typography.Text>
      ))}
      <Typography.Text type="secondary">原始结构供逐字段核对：</Typography.Text>
    </Flex>
  )
}

function ControlBlockReviewSummary({
  changeSetId,
  item,
  workflowId,
  baseRevision,
  projectId,
}: {
  changeSetId: string
  item: MCPChangeItem
  workflowId: string | null
  baseRevision: number | null
  projectId: string
}) {
  const edit = item.proposed_content as ControlBlockEdit
  return (
    <Flex vertical gap={8}>
      <Alert
        showIcon
        type="info"
        title="人工接受后才会写入工作流草稿；不会发布或执行"
        description={`基线修订号 ${baseRevision ?? '未知'}；若草稿已变化，服务端会整体拒绝。`}
      />
      <Space wrap>
        <Tag color="blue">{edit.node.capability_id}</Tag>
        <Typography.Text strong>{edit.node.name}</Typography.Text>
        <Typography.Text>插入连线：{edit.edge_id}</Typography.Text>
        <Typography.Text>内联区域：{edit.regions.length}</Typography.Text>
        {workflowId ? (
          <Link to={`/projects/${projectId}/workflows?focus=${workflowId}`}>查看目标工作流</Link>
        ) : null}
        {workflowId && item.review_status === 'pending' ? (
          <ControlBlockGraphPreview
            changeSetId={changeSetId}
            projectId={projectId}
            workflowId={workflowId}
          />
        ) : null}
      </Space>
      {edit.regions.map((region) => (
        <Typography.Text key={region.id}>
          区域 {region.role}：{region.nodes.map((child) => child.name).join(' → ') || '空区域'}
        </Typography.Text>
      ))}
      <Typography.Text type="secondary">原始结构供逐字段核对：</Typography.Text>
    </Flex>
  )
}

type ControlBlockEdit = {
  edge_id: string
  node: { name: string; capability_id: string }
  regions: { id: string; role: string; nodes: { name: string }[] }[]
}

function required(value: string | null): string {
  if (!value) throw new Error('缺少 ChangeSet ID')
  return value
}
