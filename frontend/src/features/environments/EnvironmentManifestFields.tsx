import { Button, Card, Col, Form, Input, InputNumber, Row, Select, Space, Tag } from 'antd'
import { defaultEnvironmentService } from './environment-template-manifest'
import type { EnvironmentTemplateInput } from './environment-service'

type Path = Array<string | number>
export default function EnvironmentManifestFields() {
  const form = Form.useFormInstance<EnvironmentTemplateInput>()
  const services = Form.useWatch(['manifest', 'services'], form) ?? []
  const names = services.map((item) => item.name).filter(Boolean)
  return (
    <>
      <Row gutter={16}>
        <NumberField
          path={['manifest', 'default_ttl_seconds']}
          label="默认 TTL"
          min={60}
          max={86400}
        />
        <NumberField
          path={['manifest', 'maximum_ttl_seconds']}
          label="最大 TTL"
          min={60}
          max={86400}
        />
      </Row>
      <Form.List name={['manifest', 'services']}>
        {(fields, { add, remove, move }, { errors }) => (
          <Space orientation="vertical" className="environment-field-stack">
            {fields.map((field, index) => (
              <Card
                size="small"
                key={field.key}
                title={`服务 ${index + 1}`}
                extra={
                  <Space wrap>
                    <Button disabled={index === 0} onClick={() => move(index, index - 1)}>
                      上移服务
                    </Button>
                    <Button
                      disabled={index === fields.length - 1}
                      onClick={() => move(index, index + 1)}
                    >
                      下移服务
                    </Button>
                    <Button
                      danger
                      disabled={fields.length === 1}
                      onClick={() => remove(field.name)}
                    >
                      删除服务
                    </Button>
                  </Space>
                }
              >
                <ServiceFields index={field.name} names={names} />
              </Card>
            ))}
            <Form.ErrorList errors={errors} />
            <Button
              disabled={fields.length >= 5}
              onClick={() => {
                let next = fields.length + 1
                while (names.includes(`service-${next}`)) next += 1
                add(defaultEnvironmentService(`service-${next}`))
              }}
            >
              添加服务（最多5个）
            </Button>
          </Space>
        )}
      </Form.List>
      <SeedFields names={names} />
    </>
  )
}
function ServiceFields({ index, names }: { index: number; names: string[] }) {
  const form = Form.useFormInstance<EnvironmentTemplateInput>()
  const kind = Form.useWatch(
    (value: EnvironmentTemplateInput) => value.manifest?.services?.[index]?.health_check?.kind,
    form,
  )
  const name = Form.useWatch(['manifest', 'services', index, 'name'], form)
  return (
    <>
      <Row gutter={16}>
        <Col xs={24} sm={12}>
          <Form.Item name={[index, 'name']} label="服务名称" rules={[{ required: true }]}>
            <Input placeholder="小写字母、数字和连字符" maxLength={63} />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item
            name={[index, 'image']}
            label="白名单镜像（必须固定 Digest）"
            rules={[{ required: true }]}
          >
            <Input maxLength={500} />
          </Form.Item>
        </Col>
        <NumberField path={[index, 'internal_port']} label="服务端口" min={1024} max={65535} />
        <Col xs={24} sm={12}>
          <Form.Item name={[index, 'depends_on']} label="依赖服务">
            <Select
              mode="multiple"
              maxCount={4}
              options={names
                .filter((value) => value !== name)
                .map((value) => ({ value, label: value }))}
            />
          </Form.Item>
        </Col>
      </Row>
      <Form.List name={[index, 'environment']}>
        {(fields, { add, remove }) => (
          <div>
            {fields.map((field, variableIndex) => (
              <Row gutter={12} key={field.key} align="middle">
                <Col xs={24} sm={9}>
                  <Form.Item
                    name={[field.name, 'name']}
                    label={`变量${variableIndex + 1}名称`}
                    rules={[{ required: true }]}
                  >
                    <Input maxLength={128} />
                  </Form.Item>
                </Col>
                <Col xs={20} sm={11}>
                  <Form.Item name={[field.name, 'value']} label={`变量${variableIndex + 1}值`}>
                    <Input maxLength={1000} />
                  </Form.Item>
                </Col>
                <Col xs={4} sm={4}>
                  <Button danger onClick={() => remove(field.name)}>
                    删除变量
                  </Button>
                </Col>
              </Row>
            ))}
            <Button disabled={fields.length >= 32} onClick={() => add({ name: '', value: '' })}>
              添加环境变量
            </Button>
          </div>
        )}
      </Form.List>
      <Row gutter={16}>
        <Col xs={24} sm={12}>
          <Form.Item
            name={[index, 'health_check', 'kind']}
            label="健康检查"
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { value: 'http', label: 'HTTP' },
                { value: 'tcp', label: 'TCP' },
              ]}
              onChange={(value) =>
                form.setFieldValue(
                  ['manifest', 'services', index, 'health_check', 'path'],
                  value === 'tcp' ? null : '/',
                )
              }
            />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item
            name={[index, 'health_check', 'path']}
            label="健康路径"
            rules={kind === 'http' ? [{ required: true }] : []}
          >
            <Input disabled={kind === 'tcp'} />
          </Form.Item>
        </Col>
        <NumberField
          path={[index, 'health_check', 'expected_status']}
          label="预期状态码"
          min={100}
          max={599}
        />
        <NumberField
          path={[index, 'health_check', 'interval_seconds']}
          label="检查间隔（秒）"
          min={0.1}
          max={10}
          integer={false}
        />
        <NumberField
          path={[index, 'health_check', 'timeout_seconds']}
          label="检查超时（秒）"
          min={0.1}
          max={10}
          integer={false}
        />
        <NumberField
          path={[index, 'health_check', 'maximum_attempts']}
          label="最多检查次数"
          min={1}
          max={120}
        />
        <NumberField path={[index, 'cpu_millicores']} label="CPU (m)" min={100} max={2000} />
        <NumberField path={[index, 'memory_megabytes']} label="内存 (MiB)" min={64} max={2048} />
        <NumberField path={[index, 'pids_limit']} label="PID 上限" min={16} max={256} />
        <NumberField path={[index, 'user_id']} label="容器 UID" min={1} max={65535} />
        <NumberField path={[index, 'group_id']} label="容器 GID" min={1} max={65535} />
      </Row>
      <Tag>只读根文件系统 · Drop ALL · No New Privileges（固定开启）</Tag>
    </>
  )
}
function NumberField({
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
          className="environment-number"
        />
      </Form.Item>
    </Col>
  )
}
function SeedFields({ names }: { names: string[] }) {
  return (
    <Card size="small" title="预定义 Seed">
      <Form.List name={['manifest', 'seeds']}>
        {(fields, { add, remove }) => (
          <>
            {fields.map((field, index) => (
              <Row gutter={12} key={field.key} align="middle">
                <Col xs={24} sm={9}>
                  <Form.Item
                    name={[field.name, 'service']}
                    label={`Seed ${index + 1}服务`}
                    rules={[{ required: true }]}
                  >
                    <Select options={names.map((value) => ({ value, label: value }))} />
                  </Form.Item>
                </Col>
                <Col xs={20} sm={11}>
                  <Form.Item
                    name={[field.name, 'path']}
                    label={`Seed ${index + 1}路径`}
                    rules={[{ required: true }]}
                  >
                    <Input placeholder="/seed" />
                  </Form.Item>
                </Col>
                <Col xs={4} sm={4}>
                  <Button danger onClick={() => remove(field.name)}>
                    删除 Seed
                  </Button>
                </Col>
              </Row>
            ))}
            <Button
              disabled={fields.length >= 10 || names.length === 0}
              onClick={() => add({ profile: 'http_get_v1', service: names[0], path: '/' })}
            >
              添加 HTTP GET Seed（最多10个）
            </Button>
          </>
        )}
      </Form.List>
    </Card>
  )
}
