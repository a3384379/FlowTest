import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  Input,
  InputNumber,
  Radio,
  Row,
  Select,
  Space,
} from 'antd'
import {
  defaultPerformanceStep,
  performanceThresholdUnit,
  type PerformanceForm,
} from './performance-definition'
type Path = Array<string | number>
export default function PerformanceDefinitionFields() {
  return (
    <>
      <LoadFields />
      <Form.List name={['definition', 'steps']}>
        {(fields, { add, remove, move }, { errors }) => (
          <Space orientation="vertical" className="performance-field-stack">
            {fields.map((field, index) => (
              <Card
                size="small"
                key={field.key}
                title={`HTTP 步骤 ${index + 1}`}
                extra={
                  <Space wrap>
                    <Button disabled={index === 0} onClick={() => move(index, index - 1)}>
                      上移步骤
                    </Button>
                    <Button
                      disabled={index === fields.length - 1}
                      onClick={() => move(index, index + 1)}
                    >
                      下移步骤
                    </Button>
                    <Button
                      danger
                      disabled={fields.length === 1}
                      onClick={() => remove(field.name)}
                    >
                      删除步骤
                    </Button>
                  </Space>
                }
              >
                <StepFields index={field.name} />
              </Card>
            ))}
            <Form.ErrorList errors={errors} />
            <Button
              disabled={fields.length >= 20}
              onClick={() => add(defaultPerformanceStep(`请求 ${fields.length + 1}`))}
            >
              添加 HTTP 步骤（最多20个）
            </Button>
          </Space>
        )}
      </Form.List>
      <ThresholdFields />
    </>
  )
}
function NumericField({
  path,
  label,
  min,
  max,
  integer = true,
}: {
  path: Path
  label: string
  min: number
  max: number
  integer?: boolean
}) {
  return (
    <Col xs={24} sm={12} md={8}>
      <Form.Item name={path} label={label} rules={[{ required: true, message: `请填写${label}` }]}>
        <InputNumber
          min={min}
          max={max}
          precision={integer ? 0 : undefined}
          className="performance-number"
        />
      </Form.Item>
    </Col>
  )
}
function LoadFields() {
  const form = Form.useFormInstance<PerformanceForm>()
  const executor = Form.useWatch(['definition', 'executor'], form)
  const stages = Form.useWatch(['definition', 'stages'], { form, preserve: true }) ?? []
  const constantDuration =
    Form.useWatch(['definition', 'duration_seconds'], { form, preserve: true }) ?? 0
  const total =
    executor === 'constant_vus'
      ? constantDuration
      : stages.reduce((sum, item) => sum + (item.duration_seconds ?? 0), 0)
  return (
    <Card size="small" title="负载配置">
      <Form.Item name={['definition', 'executor']} label="负载模型">
        <Radio.Group
          options={[
            { label: '固定 VU', value: 'constant_vus' },
            { label: '阶梯升压', value: 'ramping_vus' },
          ]}
        />
      </Form.Item>
      <Alert
        type="info"
        title={`负载总时长 ${total} 秒`}
        description="切换模型会保留两侧输入，提交时只保存当前模型。合同上限1000 VU、3600秒；部署可配置更低的上限。"
      />
      {executor === 'constant_vus' ? (
        <Row gutter={16}>
          <NumericField path={['definition', 'vus']} label="VU" min={1} max={1000} />
          <NumericField
            path={['definition', 'duration_seconds']}
            label="持续时间（秒）"
            min={1}
            max={3600}
          />
        </Row>
      ) : (
        <>
          <Row gutter={16}>
            <NumericField path={['definition', 'start_vus']} label="起始 VU" min={0} max={1000} />
          </Row>
          <Form.List name={['definition', 'stages']}>
            {(fields, { add, remove, move }, { errors }) => (
              <>
                {fields.map((field, index) => (
                  <Card
                    size="small"
                    title={`升压阶段 ${index + 1}`}
                    key={field.key}
                    extra={
                      <Space wrap>
                        <Button disabled={index === 0} onClick={() => move(index, index - 1)}>
                          上移阶段
                        </Button>
                        <Button
                          danger
                          disabled={fields.length === 1}
                          onClick={() => remove(field.name)}
                        >
                          删除阶段
                        </Button>
                      </Space>
                    }
                  >
                    <Row gutter={16}>
                      <NumericField
                        path={[field.name, 'duration_seconds']}
                        label="升压时间（秒）"
                        min={1}
                        max={3600}
                      />
                      <NumericField
                        path={[field.name, 'target_vus']}
                        label="目标 VU"
                        min={0}
                        max={1000}
                      />
                    </Row>
                  </Card>
                ))}
                <Form.ErrorList errors={errors} />
                <Button
                  disabled={fields.length >= 20}
                  onClick={() => add({ duration_seconds: 60, target_vus: 20 })}
                >
                  添加升压阶段（最多20个）
                </Button>
              </>
            )}
          </Form.List>
        </>
      )}
      <Row gutter={16}>
        <NumericField
          path={['definition', 'graceful_stop_seconds']}
          label="优雅停止时间（秒）"
          min={0}
          max={300}
        />
      </Row>
    </Card>
  )
}
function StepFields({ index }: { index: number }) {
  return (
    <>
      <Row gutter={16}>
        <Col xs={24} sm={8}>
          <Form.Item name={[index, 'name']} label="步骤名称" rules={[{ required: true }]}>
            <Input maxLength={120} />
          </Form.Item>
        </Col>
        <Col xs={24} sm={6}>
          <Form.Item name={[index, 'method']} label="方法" rules={[{ required: true }]}>
            <Select
              options={['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].map(
                (value) => ({ value }),
              )}
            />
          </Form.Item>
        </Col>
        <Col xs={24} sm={10}>
          <Form.Item name={[index, 'url']} label="目标 URL" rules={[{ required: true }]}>
            <Input maxLength={2048} placeholder="https://api.example.com/orders" />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item
            name={[index, 'expected_statuses']}
            label="期望状态码"
            rules={[{ required: true }]}
          >
            <Select
              mode="multiple"
              maxCount={20}
              showSearch
              options={Array.from({ length: 500 }, (_, i) => ({
                value: i + 100,
                label: String(i + 100),
              }))}
            />
          </Form.Item>
        </Col>
        <NumericField
          path={[index, 'pause_seconds']}
          label="步骤间隔（秒）"
          min={0}
          max={60}
          integer={false}
        />
      </Row>
      <Form.List name={[index, 'header_pairs']}>
        {(fields, { add, remove }, { errors }) => (
          <>
            {fields.map((field, position) => (
              <Row gutter={12} key={field.key} align="middle">
                <Col xs={24} sm={9}>
                  <Form.Item
                    name={[field.name, 'name']}
                    label={`请求头${position + 1}名称`}
                    rules={[{ required: true }]}
                  >
                    <Input maxLength={128} />
                  </Form.Item>
                </Col>
                <Col xs={20} sm={11}>
                  <Form.Item name={[field.name, 'value']} label={`请求头${position + 1}值`}>
                    <Input maxLength={8192} />
                  </Form.Item>
                </Col>
                <Col xs={4} sm={4}>
                  <Button danger onClick={() => remove(field.name)}>
                    删除请求头
                  </Button>
                </Col>
              </Row>
            ))}
            <Form.ErrorList errors={errors} />
            <Button onClick={() => add({ name: '', value: '' })}>添加请求头</Button>
          </>
        )}
      </Form.List>
      <Form.Item
        name={[index, 'body_json']}
        label="请求体（JSON值，字符串使用双引号）"
        rules={[{ required: true }]}
      >
        <Input.TextArea rows={3} className="code-input" />
      </Form.Item>
    </>
  )
}
function ThresholdFields() {
  return (
    <Card size="small" title="质量阈值">
      <Form.List name={['definition', 'thresholds']}>
        {(fields, { add, remove }, { errors }) => (
          <>
            {fields.map((field, index) => (
              <Card
                size="small"
                title={`阈值 ${index + 1}`}
                key={field.key}
                extra={
                  <Button danger disabled={fields.length === 1} onClick={() => remove(field.name)}>
                    删除阈值
                  </Button>
                }
              >
                <ThresholdRow index={field.name} />
              </Card>
            ))}
            <Form.ErrorList errors={errors} />
            <Button
              disabled={fields.length >= 30}
              onClick={() =>
                add({
                  metric: 'http_req_duration',
                  aggregation: 'avg',
                  operator: '<',
                  value: 500,
                  abort_on_fail: false,
                  delay_abort_seconds: 0,
                })
              }
            >
              添加阈值（最多30个）
            </Button>
          </>
        )}
      </Form.List>
    </Card>
  )
}
function ThresholdRow({ index }: { index: number }) {
  const form = Form.useFormInstance<PerformanceForm>()
  const threshold = Form.useWatch(['definition', 'thresholds', index], form)
  const unit = performanceThresholdUnit(threshold?.metric ?? '', threshold?.aggregation ?? '')
  return (
    <Row gutter={16}>
      <Col xs={24} sm={12}>
        <Form.Item name={[index, 'metric']} label="指标名称" rules={[{ required: true }]}>
          <Input maxLength={160} placeholder="http_req_duration" />
        </Form.Item>
      </Col>
      <Col xs={24} sm={12}>
        <Form.Item
          name={[index, 'aggregation']}
          label="聚合方法"
          rules={[{ required: true }]}
          extra="avg / med / min / max / rate / count / p(95)"
        >
          <Input />
        </Form.Item>
      </Col>
      <Col xs={24} sm={12}>
        <Form.Item name={[index, 'operator']} label="比较符">
          <Select options={['<', '<=', '>', '>='].map((value) => ({ value }))} />
        </Form.Item>
      </Col>
      <NumericField
        path={[index, 'value']}
        label={`阈值（${unit}）`}
        min={0}
        max={1_000_000_000}
        integer={false}
      />
      <Col xs={24} sm={12}>
        <Form.Item name={[index, 'abort_on_fail']} label="阈值失败处理" valuePropName="checked">
          <Checkbox
            onChange={(event) => {
              if (!event.target.checked)
                form.setFieldValue(['definition', 'thresholds', index, 'delay_abort_seconds'], 0)
            }}
          >
            失败时中止
          </Checkbox>
        </Form.Item>
      </Col>
      <NumericField
        path={[index, 'delay_abort_seconds']}
        label="延迟中止（秒）"
        min={0}
        max={3600}
      />
    </Row>
  )
}
