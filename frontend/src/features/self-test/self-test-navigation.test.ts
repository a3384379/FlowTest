import { describe, expect, it } from 'vitest'
import {
  clearSelfTestReference,
  reportSelfTestReference,
  selfTestLocation,
  selfTestReportPath,
  selfTestProposalPath,
  selfTestReferenceWithContext,
  selfTestPath,
  carrySelfTestContext,
} from './self-test-navigation'

const batchId = '00000000-0000-4000-8000-000000000001'
describe('self-test URL boundaries', () => {
  it('carries only validated internal filters across review, assets and reports', () => {
    const origin = new URLSearchParams(
      `tab=selftest&mode=native&batch=${batchId}&category=engine&verification=matched&page=2&cursor=${batchId}`,
    )
    const reference = selfTestReferenceWithContext({ batchId, scenarioId: 'ST-ENGINE-001' }, origin)
    const review = selfTestProposalPath('project', 'flow_spec', batchId, reference)
    const asset = carrySelfTestContext(
      '/projects/project/workflows?focus=asset&version=3',
      new URLSearchParams(review.split('?')[1]),
    )
    const restored = selfTestPath(
      'project',
      reportSelfTestReference(new URLSearchParams(asset.split('?')[1]))!,
    )
    const result = new URLSearchParams(restored.split('?')[1])
    expect(result.get('mode')).toBe('native')
    expect(result.get('category')).toBe('engine')
    expect(result.get('page')).toBe('2')
    expect(result.get('cursor')).toBe(batchId)
  })
  it.each([
    'https://outside.example/path',
    'tab=selftest&mode=native&return=https://outside.example',
    'tab=selftest&mode=native&page=0',
    'tab=selftest&mode=native&mode=mcp_generation',
  ])('drops unsafe return context %s', (value) => {
    const params = new URLSearchParams({ selfTestBatch: batchId, selfTestReturn: value })
    expect(reportSelfTestReference(params)).toEqual({ batchId })
    expect(selfTestPath('project', reportSelfTestReference(params)!)).toMatch(
      /^\/projects\/project\/quality\?/,
    )
  })
  it('keeps quality as default and unknown modes at the MCP view without commands', () => {
    expect(selfTestLocation(new URLSearchParams()).active).toBe(false)
    expect(selfTestLocation(new URLSearchParams('tab=selftest&mode=unknown')).mode).toBe(
      'mcp_generation',
    )
  })
  it.each([
    'page=0',
    'page=NaN',
    'page=1001',
    'batch=execution-id',
    'verification=passed',
    'scenario=../other',
  ])('rejects an invalid scope %s', (search) => {
    expect(selfTestLocation(new URLSearchParams(search)).error).toBeTruthy()
  })
  it('preserves the exact execution and control location when adding a batch reference', () => {
    const path = selfTestReportPath(
      'project',
      {
        executionId: 'execution',
        nodeId: 'control',
        attempt: 2,
        controlKind: 'iteration',
        controlOrdinal: 0,
        instanceId: '__nested_request__:child',
        instanceAttempt: 1,
      },
      { batchId, scenarioId: 'ST-MCP-023' },
    )
    const params = new URLSearchParams(path.split('?')[1])
    expect(params.get('execution')).toBe('execution')
    expect(params.get('node')).toBe('control')
    expect(params.get('control_ordinal')).toBe('0')
    expect(params.get('attempt')).toBe('2')
    expect(params.get('instance')).toBe('__nested_request__:child')
    expect(reportSelfTestReference(params)).toEqual({ batchId, scenarioId: 'ST-MCP-023' })
    clearSelfTestReference(params)
    expect(params.has('selfTestBatch')).toBe(false)
    expect(params.get('execution')).toBe('execution')
  })
  it('uses existing proposal routes and cannot build an arbitrary return URL', () => {
    expect(selfTestProposalPath('project', 'flow_spec', 'proposal', { batchId })).toContain(
      '/workflows?proposal=proposal&selfTestBatch=',
    )
    expect(selfTestProposalPath('project', 'controlled_write', 'proposal', { batchId })).toContain(
      '/mcp-changes?focus=proposal&selfTestBatch=',
    )
    expect(reportSelfTestReference(new URLSearchParams('selfTestBatch=https://other'))).toBeNull()
  })
})

it('restores the original paginated scope without adding a server scenario filter', () => {
  const origin = new URLSearchParams(
    `tab=selftest&mode=mcp_generation&batch=${batchId}&page=2&category=mcp`,
  )
  const reference = selfTestReferenceWithContext({ batchId, scenarioId: 'ST-MCP-023' }, origin)
  const restored = new URLSearchParams(selfTestPath('project', reference).split('?')[1])
  expect(restored.get('page')).toBe('2')
  expect(restored.get('scenario')).toBeNull()
  expect(restored.get('category')).toBe('mcp')
  const direct = new URLSearchParams(
    selfTestPath('project', { batchId, scenarioId: 'ST-MCP-023' }).split('?')[1],
  )
  expect(direct.get('scenario')).toBe('ST-MCP-023')
  expect(selfTestLocation(direct).page).toBe(1)
})
