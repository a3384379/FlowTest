import { useQuery } from '@tanstack/react-query'
import { Button, Form, InputNumber, Select, Space, Typography } from 'antd'
import { useState } from 'react'
import type { ChangeRegressionRun } from './change-regression-service'
import {
  updateRegressionPlanWorkflow,
  type RegressionMaintenance,
} from './regression-maintenance-service'
import { listEnvironments } from '../workflows/workflow-service'

type PlanWorkflowInput = { workflow_id: string; workflow_version: number; environment_id: string }

export default function RegressionPlanWorkflowForm({
  run,
  snapshot,
  busy,
  perform,
}: {
  run: ChangeRegressionRun
  snapshot: RegressionMaintenance
  busy: boolean
  perform: (action: () => Promise<unknown>) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const environments = useQuery({
    queryKey: ['environments', run.project_id],
    queryFn: () => listEnvironments(run.project_id),
    enabled: open,
  })
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Typography.Link href={`/projects/${run.project_id}/workflows`}>
        在原流程页面发布已审核草稿
      </Typography.Link>
      <Button onClick={() => setOpen(!open)}>更新受影响流程的固定计划版本</Button>
      {open && (
        <Form<PlanWorkflowInput>
          name="maintenance-plan"
          layout="vertical"
          onFinish={(input) =>
            perform(() => updateRegressionPlanWorkflow(run.project_id, run.id, input))
          }
        >
          <Form.Item name="workflow_id" label="加入计划的受影响流程" rules={[{ required: true }]}>
            <Select
              options={snapshot.affected.affected_workflows.map((item) => ({
                value: item.workflow_id,
                label: item.workflow_id,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="workflow_version"
            label="已发布 Workflow 版本"
            rules={[{ required: true }]}
          >
            <InputNumber min={1} precision={0} />
          </Form.Item>
          <Form.Item
            name="environment_id"
            label="正式 TestPlan 运行环境"
            rules={[{ required: true }]}
          >
            <Select
              loading={environments.isLoading}
              options={(environments.data ?? []).map((item) => ({
                value: item.id,
                label: item.name,
              }))}
            />
          </Form.Item>
          <Typography.Paragraph type="secondary">
            仅更新固定计划项，不触发执行；保留该计划项已有运行参数。随后仍须维护审核和人工批准。
          </Typography.Paragraph>
          <Button htmlType="submit" loading={busy}>
            显式加入 / 更新固定版本
          </Button>
        </Form>
      )}
    </Space>
  )
}
