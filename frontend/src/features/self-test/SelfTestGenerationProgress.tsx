import { Card, Descriptions, Empty, Space, Steps, Table, Tag, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import type { SelfTestBatch, SelfTestGeneration } from './self-test-contract'
import { selfTestProposalPath, selfTestReferenceWithContext } from './self-test-navigation'

function progressItems(generation: SelfTestGeneration, batch: SelfTestBatch) {
  const stages: Record<string, number> = {
    discovering: 0,
    reading_contract: 0,
    designing: 1,
    compiling: 2,
    proposing: 2,
    awaiting_review: 3,
    publishing: 4,
    ready: 4,
  }
  const current = stages[generation.stage] ?? 0
  const terminal = ['completed', 'cancelled', 'expired'].includes(batch.phase)
  const blocked = ['blocked', 'cancelled'].includes(generation.stage) || terminal
  const proposed = generation.proposals.length > 0
  const reviewed =
    proposed && generation.proposals.every((item) => item.review_status === 'accepted')
  const published =
    generation.sources.length === batch.expected_count && Boolean(batch.resource_digest)
  const ran = batch.plan_run_ids.length > 0
  const verified = ran && Boolean(batch.sealed_at) && batch.evidence_integrity === 'complete'
  const done = [
    proposed || current > 0,
    proposed || current > 1,
    proposed,
    reviewed,
    published,
    ran && batch.phase === 'completed',
    verified,
  ]
  return [
    '契约发现',
    '设计生成',
    '流程提案',
    '待人工审核',
    '发布固定版本',
    '正式执行',
    '独立核验',
  ].map((title, index) => ({
    title,
    status: (done[index]
      ? 'finish'
      : blocked
        ? 'wait'
        : index === current || (index === 5 && ran)
          ? 'process'
          : 'wait') as 'finish' | 'wait' | 'process',
    description: done[index] ? '已有回执' : blocked ? '未完成' : undefined,
  }))
}
export default function SelfTestGenerationProgress({
  projectId,
  generation,
  batch,
}: {
  projectId: string
  generation: SelfTestGeneration
  batch: SelfTestBatch
}) {
  const [params] = useSearchParams()
  const pending = generation.proposals.filter((proposal) => proposal.review_status === 'pending')
  return (
    <div className="self-test-generation-progress">
      <div className="self-test-progress-heading">
        <Typography.Text strong>生成与运行进度</Typography.Text>
        <Typography.Text type="secondary">
          设计、审核发布、正式运行与独立核验分别记录
        </Typography.Text>
      </div>
      <Steps size="small" items={progressItems(generation, batch)} />
      <div className="self-test-generation-layout">
        <div className="self-test-evidence">
          <div className="self-test-summary self-test-metric-cards">
            <Card size="small">
              <strong>{batch.expected_count}</strong>冻结预期场景
            </Card>
            <Card size="small">
              <strong>{generation.sources.length}</strong>已发布来源
            </Card>
            <Card size="small">
              <strong>{batch.plan_run_ids.length}</strong>正式原生运行
            </Card>
          </div>
          <Card size="small" title="本轮真实提案">
            <Table
              size="small"
              pagination={false}
              scroll={{ x: 620 }}
              rowKey={(proposal) => `${proposal.change_set_id}:${proposal.item_id}`}
              dataSource={generation.proposals}
              locale={{
                emptyText: (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无真实提案" />
                ),
              }}
              columns={[
                {
                  title: '生成资产',
                  render: (_, proposal) => (
                    <Space orientation="vertical">
                      <Typography.Text>
                        {proposal.route === 'flow_spec_visual'
                          ? 'Workflow 流程提案'
                          : '受控用例提案'}
                      </Typography.Text>
                      <Typography.Text type="secondary">{proposal.change_set_id}</Typography.Text>
                    </Space>
                  ),
                },
                {
                  title: '审核状态',
                  render: (_, proposal) => (
                    <Tag
                      color={
                        proposal.review_status === 'pending'
                          ? 'warning'
                          : proposal.review_status === 'rejected'
                            ? 'error'
                            : 'blue'
                      }
                    >
                      {proposal.review_status === 'pending'
                        ? '待审核'
                        : proposal.review_status === 'rejected'
                          ? '已拒绝'
                          : '已审核'}
                    </Tag>
                  ),
                },
                {
                  title: '物化回执',
                  render: (_, proposal) =>
                    proposal.materialized_resource_id
                      ? '已关联资源，版本以固定来源为准'
                      : '尚未物化',
                },
                {
                  title: '下一步',
                  render: (_, proposal) => (
                    <Link
                      to={selfTestProposalPath(
                        projectId,
                        proposal.route === 'flow_spec_visual' ? 'flow_spec' : 'controlled_write',
                        proposal.change_set_id,
                        selfTestReferenceWithContext({ batchId: generation.batch_id }, params),
                      )}
                    >
                      查看提案
                    </Link>
                  ),
                },
              ]}
            />
          </Card>
        </div>
        <Card size="small" title="运行前置条件">
          <Descriptions
            size="small"
            column={1}
            items={[
              {
                key: 'review',
                label: '提案审核',
                children: pending.length
                  ? `${pending.length} 项待审核`
                  : generation.proposals.length
                    ? '当前回执无待审核项'
                    : '尚无提案回执',
              },
              {
                key: 'source',
                label: '固定版本',
                children: `${generation.sources.length} / ${batch.expected_count} 项来源已发布`,
              },
              {
                key: 'execute',
                label: '正式运行',
                children: batch.plan_run_ids.length
                  ? '已有真实原生 Run'
                  : '尚无正式执行，需明确确认',
              },
              {
                key: 'host',
                label: '真实宿主验收',
                children:
                  generation.generation_mode === 'host_llm_mcp' &&
                  generation.sources.some((source) => source.host_evidence)
                    ? '已有宿主来源记录，结论以独立核验为准'
                    : '未执行（NOT_RUN）',
              },
            ]}
          />
          <Typography.Text type="secondary">
            生成准备完成不授予运行权限；未审核、未发布或未确认时不会启动正式执行。
          </Typography.Text>
        </Card>
      </div>
    </div>
  )
}
