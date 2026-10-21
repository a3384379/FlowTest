import { scenarioReason, scenarioKind } from './design-review-rules'
import { confidenceLabel } from './design-confidence'
import { Button, Table, Tag } from 'antd'

import type { CoverageEntry, OracleSpec, ScenarioCandidate } from './test-engineering-service'

export function ScenarioTable({
  items,
  selected,
  disabled,
  onChange,
  oracles = [],
  inspectedId,
  onInspect,
}: {
  items: ScenarioCandidate[]
  selected: string[]
  disabled: boolean
  onChange: (ids: string[]) => void
  oracles?: OracleSpec[]
  inspectedId?: string
  onInspect?: (id: string) => void
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={{ pageSize: 10, showSizeChanger: false }}
      scroll={{ x: 880 }}
      dataSource={items}
      rowClassName={(item) => (item.id === inspectedId ? 'selected-row' : '')}
      rowSelection={{
        selectedRowKeys: selected,
        onChange: (keys) => onChange(keys.map(String)),
        getCheckboxProps: (scenario) => ({
          disabled: disabled || scenarioReason(scenario, oracles) !== null,
          name: scenarioReason(scenario, oracles)
            ? '仅设计：需要补全前置条件或可执行预期'
            : scenario.title,
        }),
      }}
      columns={[
        {
          title: '场景',
          render: (_, item) => (
            <Button
              type="link"
              onClick={() => onInspect?.(item.id)}
              aria-label={`查看场景：${item.title}`}
            >
              {item.title}
            </Button>
          ),
        },
        { title: '类型', dataIndex: 'kind', render: scenarioKind },
        { title: '预期分类', dataIndex: 'expected_category', render: categoryLabel },
        { title: '置信度', render: (_, item) => confidenceLabel(item.confidence) },
        {
          title: '可执行性',
          render: (_, item) => (
            <Tag color={scenarioReason(item, oracles) ? 'orange' : 'green'}>
              {scenarioReason(item, oracles) ? '仅设计' : '可生成草稿'}
            </Tag>
          ),
        },
        { title: '来源', render: (_, item) => `${item.evidence_refs.length} 条引用` },
      ]}
    />
  )
}

export function OracleTable({
  items,
  onEvidence,
}: {
  items: OracleSpec[]
  onEvidence?: (id: string) => void
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={{ pageSize: 8, showSizeChanger: false }}
      scroll={{ x: 760 }}
      dataSource={items}
      columns={[
        { title: '预期类型', dataIndex: 'kind', render: oracleKind },
        { title: '表达式', dataIndex: 'expression' },
        { title: '判断方式', dataIndex: 'operator', render: operatorLabel },
        {
          title: '预期值',
          render: (_, item) => (
            <pre className="test-design-json">{JSON.stringify(item.expected, null, 2)}</pre>
          ),
        },
        {
          title: '审核要求',
          render: (_, item) =>
            item.requires_review || !item.deterministic || item.confidence !== 1 ? (
              <Tag color="orange">需要复核</Tag>
            ) : (
              <Tag color="green">确定性</Tag>
            ),
        },
        {
          title: '来源证据',
          render: (_, item) =>
            item.evidence_refs.map((id, index) => (
              <Button
                key={id}
                size="small"
                onClick={() => onEvidence?.(id)}
                aria-label={`查看预期${item.id}的来源${index + 1}`}
              >
                来源 {index + 1}
              </Button>
            )),
        },
      ]}
    />
  )
}

export function CoverageTable({ items }: { items: CoverageEntry[] }) {
  return (
    <Table
      rowKey={(item) => `${item.dimension}:${item.target_ref}:${item.requirement}`}
      size="small"
      pagination={{ pageSize: 8, showSizeChanger: false }}
      scroll={{ x: 760 }}
      dataSource={items}
      columns={[
        { title: '维度', dataIndex: 'dimension' },
        { title: '评估要求', dataIndex: 'requirement' },
        { title: '目标路径', dataIndex: 'target_ref' },
        {
          title: '状态',
          render: (_, item) =>
            typeof item.covered !== 'boolean' ? (
              <Tag>未提供</Tag>
            ) : (
              <Tag color={item.covered ? 'green' : 'red'}>{item.covered ? '已覆盖' : '待补齐'}</Tag>
            ),
        },
        { title: '原因', dataIndex: 'reason' },
      ]}
    />
  )
}

function categoryLabel(value: string): string {
  const labels: Record<string, string> = {
    success: '成功响应',
    client_error: '客户端错误',
    unauthorized: '未认证',
    forbidden: '无权限',
    not_found: '不存在',
    server_error: '服务端错误',
  }
  return labels[value] ?? value
}

function oracleKind(value: string): string {
  const labels: Record<string, string> = {
    status: '状态码',
    schema: '响应结构',
    json_path: '字段值',
    expression: '表达式',
  }
  return labels[value] ?? value
}

function operatorLabel(value: string): string {
  const labels: Record<string, string> = {
    equals: '等于',
    not_equals: '不等于',
    contains: '包含',
    exists: '存在',
    matches: '匹配',
    validates: '符合结构',
  }
  return labels[value] ?? value
}
