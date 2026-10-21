import { Alert, Button, Card, Space, Table, Tag, Typography } from 'antd'
import type { TestEngineeringProposal } from './test-engineering-service'

export default function MaterializedDesignAssets({
  projectId,
  proposal,
  onOpen,
}: {
  projectId: string
  proposal: TestEngineeringProposal
  onOpen: (path: string) => void
}) {
  if (!proposal.applied) return null
  const result = proposal.materialization
  if (!result)
    return (
      <Alert
        showIcon
        type="warning"
        title="已生成资产，但该历史记录未提供资产引用"
        description="未推断工作流或用例ID，请在资产目录中核对。"
      />
    )
  const assets = result.assets ?? []
  return (
    <Card title="本次生成的资产">
      <Space orientation="vertical" className="full-width">
        <Alert
          showIcon
          type="info"
          title="生成时保存为草稿，发布和执行需分别操作"
          description="下方引用保留最初生成的资产ID；当前发布或执行状态请打开资产后确认。"
        />
        {!result.references_complete && (
          <Alert
            showIcon
            type="warning"
            title="历史资产引用不完整"
            description="仅显示能够恢复且属于当前项目的引用，不从可变的用例草稿猜测原始工作流。"
          />
        )}
        <Tag>设计记录：{result.test_design_id}</Tag>
        {assets.length > 0 ? (
          <Table
            size="small"
            rowKey="scenario_id"
            pagination={{ pageSize: 10, showSizeChanger: false }}
            scroll={{ x: 720 }}
            dataSource={assets}
            columns={[
              {
                title: '场景',
                render: (_, item) =>
                  proposal.design.scenarios.find((value) => value.id === item.scenario_id)?.title ??
                  item.scenario_id,
              },
              {
                title: '工作流',
                render: (_, item) => (
                  <Button
                    type="link"
                    onClick={() =>
                      onOpen(
                        `/projects/${encodeURIComponent(projectId)}/workflows?${new URLSearchParams({ focus: item.workflow_id })}`,
                      )
                    }
                    aria-label={`打开工作流${item.workflow_id}`}
                  >
                    {item.workflow_id}
                  </Button>
                ),
              },
              {
                title: '测试用例',
                render: (_, item) => (
                  <Button
                    type="link"
                    onClick={() =>
                      onOpen(
                        `/projects/${encodeURIComponent(projectId)}/assets?${new URLSearchParams({ type: 'case', focus: item.test_case_id, version: 'draft' })}`,
                      )
                    }
                    aria-label={`打开用例${item.test_case_id}`}
                  >
                    {item.test_case_id}
                  </Button>
                ),
              },
            ]}
          />
        ) : (
          <>
            {result.workflow_ids.map((id) => (
              <Button
                key={id}
                type="link"
                onClick={() =>
                  onOpen(
                    `/projects/${encodeURIComponent(projectId)}/workflows?${new URLSearchParams({ focus: id })}`,
                  )
                }
              >
                打开工作流 {id}
              </Button>
            ))}
            {result.test_case_ids.map((id) => (
              <Button
                key={id}
                type="link"
                onClick={() =>
                  onOpen(
                    `/projects/${encodeURIComponent(projectId)}/assets?${new URLSearchParams({ type: 'case', focus: id, version: 'draft' })}`,
                  )
                }
              >
                打开用例 {id}
              </Button>
            ))}
            {!result.workflow_ids.length && !result.test_case_ids.length && (
              <Typography.Text type="secondary">没有可恢复的受权资产引用</Typography.Text>
            )}
          </>
        )}
      </Space>
    </Card>
  )
}
