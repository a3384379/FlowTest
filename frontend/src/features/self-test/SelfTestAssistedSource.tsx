import { Alert, Descriptions, Space, Table } from 'antd'
import { Link } from 'react-router-dom'
import type { SelfTestSource } from './self-test-contract'
import { selfTestPath, selfTestProposalPath } from './self-test-navigation'

export default function SelfTestAssistedSource({
  source,
  projectId,
}: {
  source: SelfTestSource
  projectId: string
}) {
  const assisted = source.assisted
  if (!assisted) return null
  return (
    <>
      <Alert
        type="warning"
        showIcon
        title="辅助重跑，不计首次生成"
        description={
          assisted.review_mode === 'ci_fixture'
            ? '浏览器自动化测试审核者经原生审核链确认修订；不计为实际人工验收。'
            : '此批次使用已审核修订，首次生成结果保留在原批次。'
        }
      />
      <Descriptions
        title={`辅助修订来源 · 第 ${assisted.revision_number} 次`}
        size="small"
        column={1}
        items={[
          {
            key: 'batches',
            label: '批次链',
            children: (
              <Space wrap>
                <Link to={selfTestPath(projectId, { batchId: assisted.before_batch_id })}>
                  修订前批次 {assisted.before_batch_id}
                </Link>
                <Link to={selfTestPath(projectId, { batchId: assisted.origin_batch_id })}>
                  首次生成批次 {assisted.origin_batch_id}
                </Link>
              </Space>
            ),
          },
          {
            key: 'workflow',
            label: 'Workflow 版本链',
            children: `${assisted.before_workflow.id}@${assisted.before_workflow.version} → ${source.workflow.id}@${source.workflow.version}`,
          },
          {
            key: 'case',
            label: 'Case 版本链',
            children: `${assisted.before_case.id}@${assisted.before_case.version} → ${source.case.id}@${source.case.version}`,
          },
          { key: 'editor', label: '修订者', children: assisted.editor_id },
          {
            key: 'workflow-reviewer',
            label: '流程审核者',
            children: assisted.workflow_reviewer_id,
          },
          { key: 'case-reviewer', label: '用例审核者', children: assisted.case_reviewer_id },
          { key: 'source', label: '修订前来源摘要', children: assisted.before_source_digest },
          { key: 'reason', label: '修订原因摘要', children: assisted.reason_digest },
          { key: 'diff', label: '修订差异摘要', children: assisted.diff_digest },
          {
            key: 'authorization',
            label: '本次辅助授权摘要',
            children: assisted.authorization_digest,
          },
          {
            key: 'proposals',
            label: '修订前提案',
            children: (
              <Space wrap>
                {[assisted.before_workflow_proposal, assisted.before_case_proposal].map(
                  (proposal, index) => (
                    <Link
                      key={`${proposal.change_set_id}:${index}`}
                      to={selfTestProposalPath(
                        projectId,
                        proposal.route === 'flow_spec_visual' ? 'flow_spec' : 'controlled_write',
                        proposal.change_set_id,
                        { batchId: assisted.before_batch_id, scenarioId: source.scenario_id },
                      )}
                    >
                      {index === 0 ? '修订前流程提案' : '修订前用例提案'}
                    </Link>
                  ),
                )}
              </Space>
            ),
          },
        ]}
      />
      <Table
        aria-label="辅助修订差异摘要"
        size="small"
        rowKey="path"
        pagination={{ pageSize: 10, showSizeChanger: false }}
        scroll={{ x: 700 }}
        dataSource={assisted.changes}
        columns={[
          { title: '修订字段', dataIndex: 'path' },
          { title: '修订前摘要', dataIndex: 'before_digest' },
          { title: '修订后摘要', dataIndex: 'after_digest' },
        ]}
      />
    </>
  )
}
