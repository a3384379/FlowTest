import { Alert, Checkbox, Form, Input, InputNumber, Modal, Select } from 'antd'
import type { TestPlan } from '../../lib/api'
import type { UpdateTestPlanInput } from './task-plan-service'

type Fields = UpdateTestPlanInput & { scheduleMode: 'manual' | 'interval' | 'cron' }

export default function EditTestPlanDialog({
  plan,
  saving,
  onClose,
  onSave,
}: {
  plan: TestPlan
  saving: boolean
  onClose: () => void
  onSave: (input: UpdateTestPlanInput) => Promise<void>
}) {
  const [form] = Form.useForm<Fields>()
  const mode = Form.useWatch('scheduleMode', form)
  return (
    <Modal
      open
      title="编辑测试计划"
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      onCancel={onClose}
      onOk={() => form.submit()}
    >
      <Alert
        type="info"
        title="维护调度和启停。现有执行目标及固定版本保持不变；停用会阻止后续调度，正在运行的任务需单独取消。"
      />
      <Form
        form={form}
        layout="vertical"
        initialValues={{ ...plan, scheduleMode: scheduleMode(plan) }}
        onFinish={(values) => void onSave(planUpdate(values))}
      >
        <Form.Item name="name" label="计划名称" rules={[{ required: true, whitespace: true }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="description" label="说明">
          <Input.TextArea maxLength={4000} />
        </Form.Item>
        <Form.Item name="enabled" valuePropName="checked">
          <Checkbox>启用计划</Checkbox>
        </Form.Item>
        <Form.Item name="scheduleMode" label="调度方式">
          <Select
            options={[
              { value: 'manual', label: '手动' },
              { value: 'interval', label: '间隔' },
              { value: 'cron', label: 'Cron' },
            ]}
          />
        </Form.Item>
        {mode === 'interval' && (
          <Form.Item
            name="schedule_interval_seconds"
            label="间隔（秒）"
            rules={[{ required: true }]}
          >
            <InputNumber min={60} max={2592000} precision={0} />
          </Form.Item>
        )}
        {mode === 'cron' && (
          <Form.Item
            name="schedule_cron"
            label="Cron 表达式"
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={120} />
          </Form.Item>
        )}
        <Form.Item
          name="schedule_timezone"
          label="时区"
          rules={[{ required: true, whitespace: true }]}
        >
          <Input maxLength={64} />
        </Form.Item>
        <Form.Item
          name="queue_priority"
          label="优先级（0 最低，9 最高）"
          rules={[{ required: true }]}
        >
          <InputNumber min={0} max={9} precision={0} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function scheduleMode(plan: TestPlan): Fields['scheduleMode'] {
  if (plan.schedule_cron) return 'cron'
  return plan.schedule_interval_seconds === null ? 'manual' : 'interval'
}

function planUpdate(values: Fields): UpdateTestPlanInput {
  return {
    name: values.name.trim(),
    description: values.description,
    enabled: values.enabled,
    schedule_interval_seconds:
      values.scheduleMode === 'interval' ? values.schedule_interval_seconds : null,
    schedule_cron: values.scheduleMode === 'cron' ? values.schedule_cron : null,
    schedule_timezone: values.schedule_timezone,
    queue_priority: values.queue_priority,
  }
}
