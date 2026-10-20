import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { AssetCatalogRun } from '../../lib/api'
import CaseCatalogResult from './CaseCatalogResult'

const run: AssetCatalogRun = {
  status: 'failed',
  occurred_at: '2026-09-01T12:00:00Z',
  execution_id: 'old-execution',
  plan_id: null,
  plan_run_id: null,
  asset_version: 1,
  source: 'direct',
}
function show(value: AssetCatalogRun | null) {
  return render(
    <MemoryRouter initialEntries={['/projects/p/assets?assetPublication=published&casePage=3']}>
      <CaseCatalogResult projectId="p" caseId="case-one" run={value} />
    </MemoryRouter>,
  )
}

describe('case latest catalog evidence', () => {
  it('links the frozen case version and actual execution while preserving catalog scope', () => {
    show(run)
    const version = new URL(
      screen.getByRole('link', { name: '用例 v1' }).getAttribute('href')!,
      'http://test',
    )
    expect(version.searchParams.get('focus')).toBe('case-one')
    expect(version.searchParams.get('version')).toBe('1')
    expect(version.searchParams.get('casePage')).toBe('3')
    expect(version.searchParams.get('assetPublication')).toBe('published')
    expect(screen.getByRole('link', { name: '报告 →' })).toHaveAttribute(
      'href',
      '/projects/p/reports?execution=old-execution',
    )
  })
  it('shows a queued plan without inventing an execution report', () => {
    show({
      ...run,
      status: 'queued',
      execution_id: null,
      plan_id: 'plan-one',
      plan_run_id: 'run-one',
      source: 'plan',
    })
    expect(screen.getByText('排队中')).toBeVisible()
    expect(screen.queryByRole('link', { name: '报告 →' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看计划' })).toHaveAttribute(
      'href',
      '/projects/p/tasks?focus=plan-one',
    )
  })
  it('keeps an unrun asset distinct from unavailable version metadata', () => {
    const view = show(null)
    expect(screen.getByText('未运行')).toBeVisible()
    view.unmount()
    show({ ...run, asset_version: null })
    expect(screen.getByText('版本未提供')).toBeVisible()
    expect(screen.queryByRole('link', { name: /用例 v/ })).not.toBeInTheDocument()
  })
})
