import { Button, Card, Col, Form, Input, Row, Select, Space, Typography } from 'antd'
import type { FormInstance } from 'antd'
import type { ImpactCatalog } from '../impact/impact-service'
import type { RegressionFormValues, VersionPair, SourceField } from './regression-sources'

type SourceGroup = {
  field: SourceField
  label: string
  options: Array<{ value: string; label: string }>
  limit: number
}

export default function RegressionSourcesEditor({
  form,
  catalog,
  disabled,
}: {
  form: FormInstance<RegressionFormValues>
  catalog?: ImpactCatalog
  disabled: boolean
}) {
  const graphql = Form.useWatch('graphql_pairs', form) as VersionPair[] | undefined
  const grpc = Form.useWatch('grpc_pairs', form) as VersionPair[] | undefined
  const openapiOptions = (catalog?.targets ?? [])
    .filter((item) => item.target_type === 'openapi_contract')
    .map((item) => ({ value: item.id, label: `${item.name} · v${item.version ?? '未提供'}` }))
  const schemaOptions = (protocol: 'graphql' | 'grpc') =>
    (catalog?.schemas ?? [])
      .filter((item) => item.protocol === protocol)
      .map((item) => ({ value: item.id, label: `${item.name} · v${item.version}` }))
  const groups: SourceGroup[] = [
    { field: 'openapi_pairs', label: 'OpenAPI', options: openapiOptions, limit: 20 },
    {
      field: 'graphql_pairs',
      label: 'GraphQL',
      options: schemaOptions('graphql'),
      limit: 20 - (grpc?.length ?? 0),
    },
    {
      field: 'grpc_pairs',
      label: 'Proto / gRPC',
      options: schemaOptions('grpc'),
      limit: 20 - (graphql?.length ?? 0),
    },
  ]
  return (
    <Space orientation="vertical" className="full-width">
      <Typography.Paragraph type="secondary">
        至少提供一种来源，可组合 Git Diff、OpenAPI、GraphQL 与 Proto 版本对比。只解析已有版本和受限
        diff，不执行仓库命令；切换或添加来源保留未提交输入。
      </Typography.Paragraph>
      <Form.Item
        name="git_diff"
        label="Git Diff"
        extra="可选；也可仅选择下面的版本对比。最大 2 MB。"
      >
        <Input.TextArea
          aria-label="Git Diff"
          rows={7}
          maxLength={2097152}
          placeholder="粘贴受限的标准 diff --git 内容"
        />
      </Form.Item>
      {!catalog && (
        <Typography.Text type="secondary">
          当前无法选择版本对比，已有输入保留；请核对编辑权限与版本目录读取状态。
        </Typography.Text>
      )}
      {groups.map((group) => (
        <VersionPairList
          key={group.field}
          group={group}
          available={catalog !== undefined && !disabled}
        />
      ))}
    </Space>
  )
}

function VersionPairList({ group, available }: { group: SourceGroup; available: boolean }) {
  return (
    <Card size="small" title={`${group.label} 版本对比（可选）`}>
      <Form.List name={group.field}>
        {(fields, { add, remove }) => (
          <>
            {fields.map((field, index) => (
              <Row gutter={12} key={field.key} align="top">
                <Col xs={24} md={10}>
                  <Form.Item
                    name={[field.name, 'baseline']}
                    label={`${group.label} 基线 ${index + 1}`}
                  >
                    <Select
                      allowClear
                      showSearch
                      optionFilterProp="label"
                      aria-label={`${group.label} 基线 ${index + 1}`}
                      options={group.options}
                      disabled={!available}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={10}>
                  <Form.Item
                    name={[field.name, 'current']}
                    label={`${group.label} 当前版本 ${index + 1}`}
                  >
                    <Select
                      allowClear
                      showSearch
                      optionFilterProp="label"
                      aria-label={`${group.label} 当前版本 ${index + 1}`}
                      options={group.options}
                      disabled={!available}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={4}>
                  <Button
                    danger
                    aria-label={`删除 ${group.label} 对比 ${index + 1}`}
                    onClick={() => remove(field.name)}
                  >
                    删除对比
                  </Button>
                </Col>
              </Row>
            ))}
            <Button disabled={!available || fields.length >= group.limit} onClick={() => add({})}>
              添加 {group.label} 对比
            </Button>
          </>
        )}
      </Form.List>
    </Card>
  )
}
