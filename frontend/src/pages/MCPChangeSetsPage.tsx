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
import { apiErrorMessage } from '../lib/api'

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
            按精确 ChangeSet ID 审核工作流控制块、Test Design、TestCase 与 TestPlan 更新。
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
                  <ControlBlockReviewSummary
                    item={item}
                    workflowId={data.workflow_id ?? item.target_resource_id ?? null}
                    baseRevision={data.base_revision ?? null}
                    projectId={data.project_id}
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

function ControlBlockReviewSummary({
  item,
  workflowId,
  baseRevision,
  projectId,
}: {
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
