import { describe, expect, it } from 'vitest'
import { defaultReportPeriod, parseReportScope } from './report-scope'

describe('report query scope', () => {
  it('uses UTC calendar days across a local timezone boundary', () => {
    expect(defaultReportPeriod(new Date('2026-02-02T04:00:00+08:00'))).toEqual({
      from: '2026-01-26',
      to: '2026-02-01',
    })
    const result = parseReportScope(
      new URLSearchParams(
        'reportFrom=2026-02-01&reportTo=2026-02-02&reportStatus=queued&reportSource=case&reportPage=3',
      ),
    )
    expect(result.scope).toEqual(
      expect.objectContaining({
        started_from: '2026-02-01T00:00:00.000Z',
        started_until: '2026-02-03T00:00:00.000Z',
        status: 'queued',
        source: 'case',
      }),
    )
    expect(result.page).toBe(3)
  })
  it.each([
    'reportFrom=2026-02-30&reportTo=2026-03-01',
    'reportFrom=2026-02-01',
    'reportFrom=2026-03-01&reportTo=2026-02-01',
    'reportFrom=2026-01-01&reportTo=2026-04-01',
    'reportStatus=unknown',
    'reportSource=unknown',
    'reportEnvironment=invalid',
  ])('rejects an invalid shared URL instead of silently broadening it: %s', (query) => {
    const parsed = parseReportScope(new URLSearchParams(query))
    expect(parsed.scope).toBeNull()
    expect(parsed.error).toBeTruthy()
  })
  it('preserves historical source IDs and accepts the full 90 day window', () => {
    const id = '00000000-0000-4000-8000-000000000123'
    const parsed = parseReportScope(
      new URLSearchParams(
        `reportFrom=2026-01-01&reportTo=2026-03-31&reportCase=${id}&reportPlan=${id}`,
      ),
    )
    expect(parsed.error).toBeNull()
    expect(parsed.scope).toEqual(
      expect.objectContaining({ source_case_id: id, source_plan_id: id }),
    )
  })
})
