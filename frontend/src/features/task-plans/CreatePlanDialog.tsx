import { Form, Input, InputNumber, Modal, Select } from 'antd'
import TestPlanTargetSelect from './TestPlanTargetSelect'
import type {
  CreateTestPlanInput,
  TestPlanTargetAsset,
  TestPlanTargetType,
} from './task-plan-service'

export default function CreatePlanDialog({
  open,
  workflows,
  environments,
  testCases,
  testSuites,
  submitting,
  onClose,
  onCreate,
}: {
  open: boolean
  workflows: TestPlanTargetAsset[]
  environments: Array<{ id: string; name: string }>
  testCases: TestPlanTargetAsset[]
  testSuites: TestPlanTargetAsset[]
  submitting: boolean
  onClose: () => void
  onCreate: (input: CreateTestPlanInput) => Promise<void>
}) {
  type PlanForm = Omit<
    CreateTestPlanInput,
    'intervalSeconds' | 'environmentId' | 'cronExpression'
  > & {
    environmentId?: string
    scheduleMode: 'manual' | 'interval' | 'cron'
    intervalMinutes: number | null
    cronExpression?: string
  }
  const [form] = Form.useForm<PlanForm>()
  const targetType = Form.useWatch('targetType', form) ?? 'workflow'
  const scheduleMode = Form.useWatch('scheduleMode', form) ?? 'manual'
  const targetAssets = { workflow: workflows, case: testCases, suite: testSuites }
  return (
    <Modal
      title="新建测试计划"
      open={open}
      style={{ top: 24 }}
      styles={{ body: { maxHeight: 'calc(100dvh - 220px)', overflowY: 'auto' } }}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          targetType: 'workflow',
          maxRetries: 0,
          scheduleMode: 'manual',
          intervalMinutes: null,
          timezone: 'Asia/Shanghai',
          priority: 5,
        }}
        onFinish={(values) =>
          void onCreate({
            ...values,
            environmentId: values.environmentId ?? null,
            intervalSeconds:
              values.scheduleMode === 'interval' && values.intervalMinutes
                ? values.intervalMinutes * 60
                : null,
            cronExpression: values.scheduleMode === 'cron' ? (values.cronExpression ?? null) : null,
          })
        }
      >
        <Form.Item name="name" label="计划名称" rules={[{ required: true }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="targetType" label="执行目标" rules={[{ required: true }]}>
          <Select
            options={[
              { value: 'workflow', label: '工作流' },
              { value: 'case', label: '测试用例' },
              { value: 'suite', label: '测试套件' },
            ]}
            onChange={() => {
              form.setFieldValue('targetId', undefined)
              form.setFieldValue('targetVersion', undefined)
              form.setFieldValue('environmentId', undefined)
            }}
          />
        </Form.Item>
        <Form.Item name="targetId" label={targetLabel(targetType)} rules={[{ required: true }]}>
          <TestPlanTargetSelect
            key={targetType}
            type={targetType}
            label={targetLabel(targetType)}
            known={targetAssets[targetType]}
            onSelection={(asset) => form.setFieldValue('targetVersion', asset.current_version)}
          />
        </Form.Item>
        <Form.Item name="targetVersion" label="固定发布版本" rules={[{ required: true }]}>
          <InputNumber readOnly precision={0} className="full-width" />
        </Form.Item>
        {targetType === 'workflow' && (
          <Form.Item name="environmentId" label="环境" rules={[{ required: true }]}>
            <Select
              showSearch
              optionFilterProp="label"
              options={environments.map((item) => ({ value: item.id, label: item.name }))}
            />
          </Form.Item>
        )}
        <Form.Item name="scheduleMode" label="调度方式">
          <Select
            options={[
              { value: 'manual', label: '手动' },
              { value: 'interval', label: '固定间隔' },
              { value: 'cron', label: 'Cron' },
            ]}
          />
        </Form.Item>
        {scheduleMode === 'interval' && (
          <Form.Item name="intervalMinutes" label="定时间隔（分钟）" rules={[{ required: true }]}>
            <InputNumber min={1} max={43_200} precision={0} className="full-width" />
          </Form.Item>
        )}
        {scheduleMode === 'cron' && (
          <>
            <Form.Item name="cronExpression" label="Cron 表达式" rules={[{ required: true }]}>
              <Input placeholder="0 9 * * 1-5" maxLength={120} />
            </Form.Item>
            <Form.Item name="timezone" label="时区" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: 'Asia/Shanghai', label: 'Asia/Shanghai' },
                  { value: 'UTC', label: 'UTC' },
                  { value: 'Asia/Tokyo', label: 'Asia/Tokyo' },
                ]}
              />
            </Form.Item>
          </>
        )}
        <Form.Item name="priority" label="队列优先级（0 最低，9 最高）">
          <InputNumber min={0} max={9} precision={0} className="full-width" />
        </Form.Item>
        <Form.Item name="maxRetries" label="失败重试次数">
          <InputNumber min={0} max={3} precision={0} className="full-width" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function targetLabel(targetType: TestPlanTargetType) {
  const labels: Record<TestPlanTargetType, string> = {
    workflow: '工作流',
    case: '测试用例',
    suite: '测试套件',
  }
  return labels[targetType]
}
