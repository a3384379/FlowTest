import { AuditOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Card, Flex, Space, Tag, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'

import {
  approveMCPChangeSet,
  getMCPChangeSet,
  reviewMCPChangeItem,
  type MCPChangeItem,
} from '../features/mcp/mcp-change-set-service'
import ControlBlockGraphPreview from '../features/mcp/ControlBlockGraphPreview'
import ControlWorkflowGraphPreview from '../features/mcp/ControlWorkflowGraphPreview'
import { apiErrorMessage, type WorkflowDefinition } from '../lib/api'

export default function MCPChangeSetsPage() {
  const [searchParams] = useSearchParams()
  const focusId = searchParams.get('focus')
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const changeSet = useQuery({
    queryKey: ['mcp-change-set', focusId],
    queryFn: () => getMCPChangeSet(required(focusId)),
    enabled: Boolean(focusId),
  })
  const approve = useMutation({
    mutationFn: () => approveMCPChangeSet(required(focusId), '前端人工批准'),
  })
  const review = useMutation({
    mutationFn: ({ itemId, decision }: { itemId: string; decision: 'accept' | 'reject' }) =>
      reviewMCPChangeItem(
        required(focusId),
        itemId,
        decision,
        changeSet.data?.data.approval?.id ?? null,
      ),
  })

  async function refresh(): Promise<void> {
    await queryClient.invalidateQueries({ queryKey: ['mcp-change-set', focusId] })
  }

  async function approveChangeSet(): Promise<void> {
    try {
      await approve.mutateAsync()
      await refresh()
      void message.success('MCP 变更集已完成人工批准')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function reviewItem(itemId: string, decision: 'accept' | 'reject'): Promise<void> {
    try {
      await review.mutateAsync({ itemId, decision })
      await refresh()
      if (
        decision === 'accept' &&
        data?.items.some((item) => item.id === itemId && item.item_type === 'workflow')
      )
        await queryClient.invalidateQueries({ queryKey: ['workflows', data.project_id] })
      void message.success(decision === 'accept' ? '变更项已接受并物化' : '变更项已拒绝')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  const data = changeSet.data?.data
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
      {changeSet.isError ? (
        <Alert showIcon type="error" title={apiErrorMessage(changeSet.error)} />
      ) : null}
      <Card
        loading={changeSet.isLoading}
        title={data?.title ?? '受控变更集'}
        extra={data ? <Tag>{data.status}</Tag> : null}
      >
        {data ? (
          <Flex vertical gap={12}>
            <Space wrap>
              <Tag color="blue">{data.governance.risk_level}</Tag>
              <Typography.Text code>{data.id}</Typography.Text>
            </Space>
            {data.governance.manual_approval_required && !data.approval ? (
              <Alert
                showIcon
                type="warning"
                title="高风险变更必须先人工批准"
                action={
                  <Button
                    icon={<AuditOutlined />}
                    loading={approve.isPending}
                    onClick={() => void approveChangeSet()}
                  >
                    批准变更集
                  </Button>
                }
              />
            ) : null}
            {data.items.map((item) => (
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
                        disabled={review.isPending}
                        onClick={() => void reviewItem(item.id, 'reject')}
                      >
                        拒绝
                      </Button>
                      <Button
                        type="primary"
                        disabled={
                          review.isPending ||
                          (data.governance.manual_approval_required && !data.approval)
                        }
                        onClick={() => void reviewItem(item.id, 'accept')}
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
                <pre className="code-preview">{JSON.stringify(item.proposed_content, null, 2)}</pre>
              </Card>
            ))}
          </Flex>
        ) : null}
      </Card>
    </Flex>
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
        {item.materialized_resource_id ? (
          <Link to={`/projects/${projectId}/workflows?focus=${item.materialized_resource_id}`}>
            查看已创建草稿
          </Link>
        ) : null}
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
