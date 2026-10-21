import { Table, Tag } from 'antd'

import type { CoverageEntry, OracleSpec, ScenarioCandidate } from './test-engineering-service'

export function ScenarioTable({
  items,
  selected,
  disabled,
  onChange,
}: {
  items: ScenarioCandidate[]
  selected: string[]
  disabled: boolean
  onChange: (ids: string[]) => void
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={items}
      rowSelection={{
        selectedRowKeys: selected,
        onChange: (keys) => onChange(keys.map(String)),
        getCheckboxProps: (scenario) => ({
          disabled: disabled || !materializableScenario(scenario),
          name: materializableScenario(scenario)
            ? scenario.title
            : '仅设计：需要补全前置条件或可执行 Oracle',
        }),
      }}
      columns={[
        { title: 'Kind', dataIndex: 'kind' },
        { title: '标题', dataIndex: 'title' },
        {
          title: 'Location',
          render: (_: unknown, scenario: ScenarioCandidate) =>
            scenario.mutations.map((mutation) => mutation.location).join(', ') || 'request',
        },
        {
          title: 'Parameter Path',
          render: (_: unknown, scenario: ScenarioCandidate) =>
            scenario.mutations.map((mutation) => mutation.path).join(', ') || '-',
        },
        {
          title: 'Mutation',
          render: (_: unknown, scenario: ScenarioCandidate) =>
            scenario.mutations.map((mutation) => mutation.operation).join(', ') || '-',
        },
        {
          title: '预期分类',
          dataIndex: 'expected_category',
          render: (value: string) => <Tag>{value}</Tag>,
        },
        {
          title: '可执行性',
          render: (_: unknown, scenario: ScenarioCandidate) =>
            materializableScenario(scenario) ? (
              <Tag color="green">可物化</Tag>
            ) : (
              <Tag color="orange">仅设计</Tag>
            ),
        },
        {
          title: 'Auth Mode',
          render: (_: unknown, scenario: ScenarioCandidate) =>
            scenario.request.auth_disabled ? 'disabled' : 'inherit',
        },
        {
          title: 'Suppression',
          render: (_: unknown, scenario: ScenarioCandidate) => suppressionSummary(scenario) || '无',
        },
        {
          title: 'Design-only 原因',
          render: (_: unknown, scenario: ScenarioCandidate) =>
            materializableReason(scenario) ?? '-',
        },
        {
          title: 'Evidence',
          render: (_: unknown, scenario: ScenarioCandidate) => scenario.evidence_refs.length,
        },
      ]}
    />
  )
}

export function OracleTable({ items }: { items: OracleSpec[] }) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={items}
      columns={[
        { title: 'Kind', dataIndex: 'kind' },
        { title: 'Operator', dataIndex: 'operator' },
        { title: 'Expected', dataIndex: 'expected', render: (value) => JSON.stringify(value) },
        { title: 'Evidence', render: (_, item) => item.evidence_refs.length },
        {
          title: 'Review',
          render: (_, item) =>
            item.requires_review ? <Tag color="orange">需要</Tag> : <Tag color="green">确定性</Tag>,
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
      pagination={{ pageSize: 8 }}
      dataSource={items}
      columns={[
        { title: 'Dimension', dataIndex: 'dimension' },
        { title: 'Requirement', dataIndex: 'requirement', ellipsis: true },
        { title: 'Scope / Target', dataIndex: 'target_ref', ellipsis: true },
        {
          title: '状态',
          dataIndex: 'covered',
          render: (value: boolean) =>
            value ? <Tag color="green">已覆盖</Tag> : <Tag color="red">Gap</Tag>,
        },
      ]}
    />
  )
}

function materializableScenario(scenario: ScenarioCandidate): boolean {
  return (
    !scenario.requires_review &&
    scenario.deterministic &&
    !scenario.mutations.some(
      (mutation) => mutation.location === 'path' && mutation.operation === 'omit',
    )
  )
}

function materializableReason(scenario: ScenarioCandidate): string | null {
  if (scenario.requires_review) return '证据冲突、敏感测试数据或前置条件待审核'
  if (!scenario.deterministic) return '缺少确定性输入或 Oracle'
  if (
    scenario.mutations.some(
      (mutation) => mutation.location === 'path' && mutation.operation === 'omit',
    )
  ) {
    return '必填 Path omission 无法表示为真实 HTTP 请求'
  }
  return null
}

function suppressionSummary(scenario: ScenarioCandidate): string {
  const omitted = scenario.mutations
    .filter(
      (mutation) =>
        mutation.operation === 'omit' && ['header', 'query', 'cookie'].includes(mutation.location),
    )
    .map((mutation) => `${mutation.location}:${mutation.path.replace(/^[^.]+\./, '')}`)
  if (scenario.request.auth_disabled) omitted.unshift('auth:disabled')
  return omitted.join('、')
}
