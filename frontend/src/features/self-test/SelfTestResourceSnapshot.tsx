import { Alert, Descriptions, Table, Typography } from 'antd'
import type { SelfTestBatch } from './self-test-contract'

export default function SelfTestResourceSnapshot({
  snapshot,
}: {
  snapshot: SelfTestBatch['resource_snapshot']
}) {
  if (!snapshot)
    return <Alert type="warning" showIcon title="尚无完整发布资源快照，不能执行已发布产物。" />
  return (
    <div className="self-test-evidence">
      <Descriptions
        size="small"
        column={1}
        items={[
          {
            key: 'suite',
            label: 'Suite 固定版本',
            children: `${snapshot.suite.id}@${snapshot.suite.version}`,
          },
          {
            key: 'suite-digest',
            label: 'Suite 摘要',
            children: <Typography.Text code>{snapshot.suite.fingerprint}</Typography.Text>,
          },
          { key: 'plan', label: '原生计划', children: snapshot.plan_id },
        ]}
      />
      <Table
        size="small"
        pagination={false}
        rowKey={(row) => `${row.scenario_id}:${row.variant_key}`}
        dataSource={snapshot.cases}
        scroll={{ x: 1000, y: 320 }}
        columns={[
          { title: '冻结场景', render: (_, row) => `${row.scenario_id} / ${row.variant_key}` },
          { title: 'Case 固定版本', render: (_, row) => `${row.case.id}@${row.case.version}` },
          {
            title: 'Workflow 固定版本',
            render: (_, row) => `${row.workflow.id}@${row.workflow.version}`,
          },
          { title: '固定环境', dataIndex: 'environment_id' },
          { title: '执行目标快照摘要', dataIndex: 'target_snapshot_digest' },
        ]}
      />
    </div>
  )
}
