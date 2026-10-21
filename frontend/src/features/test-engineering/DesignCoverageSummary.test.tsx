import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import DesignCoverageSummary from './DesignCoverageSummary'
import type { CoverageEntry } from './test-engineering-service'

const entry: CoverageEntry = {
  target_ref: 'orders.create',
  dimension: 'endpoint',
  requirement: 'normal',
  covered: true,
  evidence_refs: [],
  reason: 'explicit',
  recommended_scenario_kind: 'happy_path',
  priority: 'high',
}

describe('design coverage denominator', () => {
  it('keeps no evaluable items distinct from complete coverage', () => {
    render(<DesignCoverageSummary entries={[]} />)
    expect(screen.getByText('无可评估项')).toBeVisible()
    expect(screen.getByText('已覆盖 0 / 0 项')).toBeVisible()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.queryByText('100%')).not.toBeInTheDocument()
  })
  it('does not manufacture a success gauge for absent legacy coverage', () => {
    render(<DesignCoverageSummary />)
    expect(screen.getByText('未评估：覆盖数据未提供')).toBeVisible()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })
  it.each([true, false])('reports one evaluated item with covered=%s', (covered) => {
    render(<DesignCoverageSummary entries={[{ ...entry, covered }]} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', covered ? '100' : '0')
    expect(screen.getByText(`已覆盖 ${covered ? 1 : 0} / 1 项`)).toBeVisible()
  })
})
