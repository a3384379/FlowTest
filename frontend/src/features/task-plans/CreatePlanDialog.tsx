import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Typography,
} from 'antd'
import type { FormInstance } from 'antd'
import { apiErrorMessage, apiErrorTraceId } from '../../lib/api'
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
  error,
}: {
  open: boolean
  workflows: TestPlanTargetAsset[]
  environments: Array<{ id: string; name: string }>
  testCases: TestPlanTargetAsset[]
  testSuites: TestPlanTargetAsset[]
  submitting: boolean
  error?: unknown
  onClose: () => void
  onCreate: (input: CreateTestPlanInput) => Promise<void>
}) {
  const [form] = Form.useForm<PlanForm>()
  const scheduleMode = Form.useWatch('scheduleMode', form) ?? 'manual'
  return (
    <Modal
      title="新建测试计划"
      okText="创建计划"
      cancelText="取消"
      open={open}
      width={880}
      style={{ top: 24 }}
      styles={{ body: { maxHeight: 'calc(100dvh - 220px)', overflowY: 'auto' } }}
      confirmLoading={submitting}
      closable={!submitting}
      mask={{ closable: !submitting }}
      keyboard={!submitting}
      cancelButtonProps={{ disabled: submitting }}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
      afterClose={() => form.resetFields()}
    >
      {Boolean(error) && (
        <Alert
          showIcon
          type="error"
          title={apiErrorMessage(error)}
          description={apiErrorTraceId(error)}
        />
      )}
      <Form
        form={form}
        layout="vertical"
        disabled={submitting}
        initialValues={{
          items: [{ targetType: 'workflow', maxRetries: 0 }],
          scheduleMode: 'manual',
          intervalMinutes: null,
          timezone: 'Asia/Shanghai',
          priority: 5,
        }}
        onFinish={(values) =>
          void onCreate({
            name: values.name.trim(),
            items: values.items.map((item) => ({
              ...item,
              environmentId: item.targetType === 'workflow' ? (item.environmentId ?? null) : null,
            })),
            timezone: values.timezone,
            priority: values.priority,
            intervalSeconds:
              values.scheduleMode === 'interval' && values.intervalMinutes
                ? values.intervalMinutes * 60
                : null,
            cronExpression: values.scheduleMode === 'cron' ? (values.cronExpression ?? null) : null,
          })
        }
      >
        <Form.Item name="name" label="计划名称" rules={[{ required: true, whitespace: true }]}>
          <Input maxLength={200} />
        </Form.Item>
        <PlanItems
          form={form}
          targetAssets={{ workflow: workflows, case: testCases, suite: testSuites }}
          environments={environments}
        />
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

type PlanForm = Omit<CreateTestPlanInput, 'intervalSeconds' | 'cronExpression'> & {
  scheduleMode: 'manual' | 'interval' | 'cron'
  intervalMinutes: number | null
  cronExpression?: string
}

type PlanTargets = Record<TestPlanTargetType, TestPlanTargetAsset[]>
type PlanEnvironment = { id: string; name: string }

function PlanItems({
  form,
  targetAssets,
  environments,
}: {
  form: FormInstance<PlanForm>
  targetAssets: PlanTargets
  environments: PlanEnvironment[]
}) {
  return (
    <Form.List
      name="items"
      rules={[
        {
          validator: async (_, items: PlanForm['items']) => {
            if (!items?.length || items.length > 100) throw new Error('需要1至100个执行项')
          },
        },
      ]}
    >
      {(fields, { add, remove, move }, { errors }) => (
        <Space orientation="vertical" className="full-width" size={16}>
          <Typography.Text>
            执行项（{fields.length}/100）：按下方顺序编组，选择时固定当前发布版本。
          </Typography.Text>
          {fields.map((field, index) => (
            <Card
              key={field.key}
              size="small"
              title={`执行项 ${index + 1}`}
              role="group"
              aria-label={`执行项 ${index + 1}`}
              extra={
                <Space wrap>
                  <Button
                    aria-label={`上移执行项 ${index + 1}`}
                    disabled={index === 0}
                    onClick={() => move(index, index - 1)}
                  >
                    上移
                  </Button>
                  <Button
                    aria-label={`下移执行项 ${index + 1}`}
                    disabled={index === fields.length - 1}
                    onClick={() => move(index, index + 1)}
                  >
                    下移
                  </Button>
                  <Button
                    danger
                    aria-label={`删除执行项 ${index + 1}`}
                    disabled={fields.length === 1}
                    onClick={() => remove(index)}
                  >
                    删除
                  </Button>
                </Space>
              }
            >
              <PlanItemFields
                form={form}
                index={field.name}
                targetAssets={targetAssets}
                environments={environments}
              />
            </Card>
          ))}
          <Form.ErrorList errors={errors} />
          <Button
            onClick={() => add({ targetType: 'workflow', maxRetries: 0 })}
            disabled={fields.length >= 100}
          >
            添加执行项
          </Button>
        </Space>
      )}
    </Form.List>
  )
}

function PlanItemFields({
  form,
  index,
  targetAssets,
  environments,
}: {
  form: FormInstance<PlanForm>
  index: number
  targetAssets: PlanTargets
  environments: PlanEnvironment[]
}) {
  const type: TestPlanTargetType = Form.useWatch(['items', index, 'targetType'], form) ?? 'workflow'
  function changeType() {
    for (const key of ['targetId', 'targetVersion', 'environmentId'] as const)
      form.setFieldValue(['items', index, key], undefined)
  }
  return (
    <>
      <Form.Item name={[index, 'targetType']} label="执行目标" rules={[{ required: true }]}>
        <Select
          options={[
            { value: 'workflow', label: '工作流' },
            { value: 'case', label: '测试用例' },
            { value: 'suite', label: '测试套件' },
          ]}
          onChange={changeType}
        />
      </Form.Item>
      <Form.Item name={[index, 'targetId']} label={targetLabel(type)} rules={[{ required: true }]}>
        <TestPlanTargetSelect
          key={type}
          type={type}
          label={targetLabel(type)}
          known={targetAssets[type as TestPlanTargetType]}
          onSelection={(asset) =>
            form.setFieldValue(['items', index, 'targetVersion'], asset.current_version)
          }
        />
      </Form.Item>
      <Form.Item
        name={[index, 'targetVersion']}
        label="固定发布版本"
        rules={[{ required: true, type: 'integer', min: 1 }]}
      >
        <InputNumber readOnly precision={0} className="full-width" />
      </Form.Item>
      {type === 'workflow' ? (
        <Form.Item name={[index, 'environmentId']} label="环境" rules={[{ required: true }]}>
          <Select
            showSearch
            optionFilterProp="label"
            options={environments.map((e) => ({ value: e.id, label: e.name }))}
          />
        </Form.Item>
      ) : (
        <Alert type="info" showIcon title="流程版本及环境继承所选用例或套件的固定发布配置" />
      )}
      <Form.Item
        name={[index, 'maxRetries']}
        label="失败重试次数"
        rules={[{ required: true, type: 'integer', min: 0, max: 3 }]}
      >
        <InputNumber min={0} max={3} precision={0} className="full-width" />
      </Form.Item>
    </>
  )
}
