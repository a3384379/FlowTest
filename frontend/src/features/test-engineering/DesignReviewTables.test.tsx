import { render, screen, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { describe, expect, it, vi } from 'vitest'

import { CoverageTable, ScenarioTable } from './DesignReviewTables'
import type { CoverageEntry, OracleSpec, ScenarioCandidate } from './test-engineering-service'

const scenario: ScenarioCandidate = {
  id: 'definitive',
  kind: 'happy_path',
  title: '明确状态码预期',
  request_body: {},
  request: {
    path_parameters: {},
    query_parameters: {},
    headers: {},
    cookies: {},
    body: null,
    auth_disabled: false,
  },
  mutations: [],
  expected_category: 'success',
  negative: false,
  evidence_refs: ['contract'],
  confidence: 1,
  deterministic: true,
  requires_review: false,
  tags: [],
}
const oracle: OracleSpec = {
  id: 'status',
  kind: 'status',
  expression: '$.status',
  operator: 'equals',
  expected: 201,
  confidence: 1,
  evidence_refs: ['contract'],
  source_type: 'contract',
  deterministic: true,
  requires_review: false,
  applies_to: [scenario.id],
}

function table(items: ScenarioCandidate[], oracles: OracleSpec[]) {
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <ScenarioTable
        items={items}
        oracles={oracles}
        selected={[]}
        disabled={false}
        onChange={vi.fn()}
      />
    </ConfigProvider>,
  )
}
function row(title: string) {
  return within(screen.getByText(title, { exact: true }).closest('tr')!)
}

describe('scenario materialization eligibility', () => {
  it('keeps weak confidence and missing status oracles distinct from executable scenarios', () => {
    const weak = { ...scenario, id: 'weak', title: '低置信度场景', confidence: 0.4 }
    const missing = { ...scenario, id: 'missing', title: '缺少状态码预期' }
    table(
      [scenario, weak, missing],
      [oracle, { ...oracle, id: 'weak-oracle', applies_to: [weak.id] }],
    )
    expect(row(scenario.title).getByRole('checkbox')).toBeEnabled()
    expect(row(scenario.title).getByText('可生成草稿')).toBeVisible()
    for (const value of [weak, missing]) {
      expect(row(value.title).getByRole('checkbox')).toBeDisabled()
      expect(row(value.title).getByText('仅设计')).toBeVisible()
    }
  })
  it.each(['conflict', 'unsupported'])(
    'does not offer a scenario with %s oracles for materialization',
    (kind) => {
      const additional: OracleSpec =
        kind === 'conflict'
          ? { ...oracle, id: 'second-status', expected: 202 }
          : { ...oracle, id: 'unsupported', kind: 'json_path', operator: 'execute' }
      table([scenario], [oracle, additional])
      expect(row(scenario.title).getByRole('checkbox')).toBeDisabled()
      expect(row(scenario.title).getByText('仅设计')).toBeVisible()
    },
  )
  it('marks absent confidence as unavailable instead of NaN or a definitive scenario', () => {
    const missing = { ...scenario, confidence: undefined as unknown as number }
    table([missing], [oracle])
    expect(row(missing.title).getByText('未提供')).toBeVisible()
    expect(row(missing.title).getByRole('checkbox')).toBeDisabled()
    expect(screen.queryByText('NaN%')).not.toBeInTheDocument()
  })
})

describe('design coverage business labels', () => {
  it('renders known coverage terms in Chinese while preserving custom requirements and paths', () => {
    const entry: CoverageEntry = {
      target_ref: 'orders.body.quantity',
      dimension: 'boundary',
      requirement: 'above maximum',
      covered: true,
      evidence_refs: [],
      reason: '',
      recommended_scenario_kind: null,
      priority: 'high',
    }
    render(
      <CoverageTable
        items={[
          entry,
          { ...entry, dimension: 'response_status', requirement: 'status 400' },
          { ...entry, dimension: 'enum', requirement: 'enum value enterprise-v2' },
          { ...entry, dimension: 'schema', requirement: 'custom English contract constraint' },
        ]}
      />,
    )
    for (const name of [
      '边界',
      '超过最大值',
      '响应状态码',
      '状态码 400',
      '枚举值 enterprise-v2',
      'custom English contract constraint',
    ])
      expect(screen.getByText(name, { exact: true })).toBeVisible()
    expect(screen.getAllByText('orders.body.quantity')).toHaveLength(4)
  })
})
