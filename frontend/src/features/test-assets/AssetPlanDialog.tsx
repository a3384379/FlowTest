import { useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Form, Input, Modal, Space, Tag, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage, type TestPlan } from '../../lib/api'
import { projectPath } from '../projects/project-routing'
import { runTestPlan } from '../task-plans/task-plan-service'
import { createAssetPlan, type PublishedAssetTarget } from './asset-workspace-service'

export default function AssetPlanDialog({
  projectId,
  targets,
  execute,
  onClose,
}: {
  projectId: string
  targets: PublishedAssetTarget[]
  execute: boolean
  onClose: () => void
}) {
  const client = useQueryClient()
  const [form] = Form.useForm<{ name: string }>()
  const [created, setCreated] = useState<TestPlan | null>(null)
  const [queued, setQueued] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [idempotencyKey] = useState(() => crypto.randomUUID())
  async function submit() {
    if (pending || queued) return
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setPending(true)
    setError(null)
    try {
      const plan = created ?? (await createAssetPlan(projectId, values.name.trim(), targets))
      setCreated(plan)
      await client.invalidateQueries({ queryKey: ['test-plans', projectId] })
      await client.invalidateQueries({ queryKey: ['asset-plans', projectId] })
      if (execute) {
        await runTestPlan(projectId, plan.id, idempotencyKey)
        setQueued(true)
        await client.invalidateQueries({ queryKey: ['asset-recent-runs', projectId] })
        await client.invalidateQueries({ queryKey: ['test-plan-runs', projectId] })
      }
    } catch (failure) {
      setError(apiErrorMessage(failure))
    } finally {
      setPending(false)
    }
  }
  const done = Boolean(created) && (!execute || queued)
  return (
    <Modal
      open
      title={execute ? '执行已发布资产' : '加入测试计划'}
      width={560}
      closable={!pending}
      mask={{ closable: !pending }}
      onCancel={onClose}
      footer={
        <Space>
          <Button disabled={pending} onClick={onClose}>
            {done ? '关闭' : '取消'}
          </Button>
          {!done && (
            <Button type="primary" loading={pending} onClick={() => void submit()}>
              {planActionLabel(execute, Boolean(created))}
            </Button>
          )}
        </Space>
      }
    >
      <Typography.Paragraph type="secondary">
        {execute
          ? '为所选版本创建手动计划并进入执行队列。'
          : '创建包含所选版本的手动计划；创建后可到任务执行页面运行。'}
        计划固定已发布版本，后续草稿修改不会改变这次执行资产。
      </Typography.Paragraph>
      <div className="asset-plan-targets">
        {targets.map((target) => (
          <div key={`${target.kind}:${target.id}`}>
            <Tag>{target.kind === 'case' ? '用例' : '套件'}</Tag>
            {target.name} <Tag color="blue">v{target.version}</Tag>
          </div>
        ))}
      </div>
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          name: `${targets[0]?.name ?? '资产'}回归 ${new Date().toLocaleString('zh-CN')}`,
        }}
      >
        <Form.Item
          name="name"
          label="计划名称"
          rules={[{ required: true, whitespace: true, max: 200 }]}
        >
          <Input disabled={Boolean(created) || pending} maxLength={200} />
        </Form.Item>
      </Form>
      <PlanFeedback projectId={projectId} created={created} queued={queued} error={error} />
    </Modal>
  )
}

function PlanFeedback({
  projectId,
  created,
  queued,
  error,
}: {
  projectId: string
  created: TestPlan | null
  queued: boolean
  error: string | null
}) {
  return (
    <>
      {error && (
        <Alert
          type="error"
          showIcon
          title={created ? '计划已创建，执行入队失败' : '创建计划失败'}
          description={error}
        />
      )}
      {created && (
        <Alert
          type={queued ? 'success' : 'info'}
          showIcon
          title={queued ? '计划已进入执行队列' : '测试计划已创建'}
          description={
            <Link to={`${projectPath(projectId, 'tasks')}?focus=${created.id}`}>
              查看 {created.name}
            </Link>
          }
        />
      )}
    </>
  )
}

function planActionLabel(execute: boolean, created: boolean): string {
  if (!execute) return '创建计划'
  return created ? '重试执行' : '创建计划并执行'
}
