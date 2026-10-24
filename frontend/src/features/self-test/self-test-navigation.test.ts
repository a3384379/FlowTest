import { describe, expect, it } from 'vitest'
import {
  clearSelfTestReference,
  reportSelfTestReference,
  selfTestLocation,
  selfTestReportPath,
  selfTestProposalPath,
} from './self-test-navigation'

const batchId = '00000000-0000-4000-8000-000000000001'
describe('self-test URL boundaries', () => {
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
