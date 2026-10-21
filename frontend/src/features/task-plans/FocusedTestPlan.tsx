import { Alert, Button, Card, Descriptions, Space, Table, Typography } from 'antd'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import type { TestPlanItem } from '../../lib/api'
import type { useTestPlans } from './use-test-plans'

export default function FocusedTestPlan({ state }: { state: ReturnType<typeof useTestPlans> }) {
  const plan = state.focusedPlan.data
  return (
    <Card
      title="选中计划详情"
      loading={state.focusedPlan.isPending}
      extra={<Button onClick={() => state.setFocusedId(null)}>关闭计划详情</Button>}
    >
      <QueryFailureNotice queries={[state.focusedPlan]} />
      <Typography.Paragraph copyable>计划 ID：{state.focusedId}</Typography.Paragraph>
      {plan && (
        <Space orientation="vertical" className="full-width" size={16}>
          <Descriptions
            column={{ xs: 1, sm: 2 }}
            items={[
              { label: '计划名称', children: plan.name },
              { label: '执行项', children: plan.items.length },
              { label: '启用状态', children: plan.enabled ? '已启用' : '已停用' },
              { label: '队列优先级', children: plan.queue_priority },
            ]}
          />
          <Alert
            showIcon
            type="info"
            title="下方为已保存的执行顺序、固定版本与重试配置；编辑计划只维护调度和启停。"
          />
          <Table<TestPlanItem>
            rowKey="id"
            size="small"
            dataSource={plan.items}
            pagination={{ pageSize: 10, showSizeChanger: false }}
            scroll={{ x: 800 }}
            columns={[
              { title: '顺序', dataIndex: 'position', render: (value: number) => value + 1 },
              { title: '目标类型', dataIndex: 'target_type', render: targetLabel },
              { title: '目标 ID', dataIndex: 'target_id' },
              {
                title: '固定发布版本',
                dataIndex: 'target_version',
                render: (value: number) => `v${value}`,
              },
              {
                title: '环境',
                render: (_, item) =>
                  item.target_type === 'workflow' ? item.environment_id : '继承固定发布配置',
              },
              {
                title: '失败重试上限',
                dataIndex: 'max_retries',
                render: (value: number) => `${value} 次`,
              },
            ]}
          />
          <Space wrap>
            <Button
              disabled={!state.canEdit || state.updatingPlan}
              onClick={() => state.setEditingPlan(plan)}
            >
              编辑所选计划
            </Button>
            <Button
              type="primary"
              disabled={!state.canEdit || state.running}
              loading={state.running}
              onClick={() => void state.execute(plan.id)}
            >
              运行所选计划
            </Button>
          </Space>
        </Space>
      )}
    </Card>
  )
}

function targetLabel(value: TestPlanItem['target_type']): string {
  return { workflow: '工作流', case: '测试用例', suite: '测试套件' }[value]
}
