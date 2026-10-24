import { describe, expect, it } from 'vitest'
import { parseAssistedLineage, parseBatch, parseHostEvidence } from './self-test-contract'
import { selfTestAssistedLineage, selfTestBatch } from './self-test-test-fixtures'
import {
  array,
  bool,
  choice,
  integer,
  nullable,
  object,
  positive,
  timestamp,
  uuid,
} from './self-test-decode'

describe('strict bounded self-test API decoder', () => {
  const parse = object({
    id: uuid,
    count: integer,
    ready: bool,
    status: choice(['pending', 'matched'] as const),
    last: nullable(timestamp),
  })
  const valid = {
    id: '00000000-0000-4000-8000-000000000001',
    count: 0,
    ready: false,
    status: 'pending',
    last: null,
  }
  it('preserves false and zero without manufacturing successful states', () => {
    expect(parse(valid)).toEqual(valid)
  })
  it.each([
    { ...valid, count: false },
    { ...valid, ready: 1 },
    { ...valid, status: 'passed' },
    { ...valid, id: 'other' },
    { ...valid, unknown: 'extension' },
  ])('rejects incompatible or unknown contract fields', (value) => {
    expect(() => parse(value)).toThrow('自测响应格式或范围无效')
  })
  it('rejects oversized collections, naive dates and invalid positive counts', () => {
    expect(() => array(integer, 2)([0, 1, 2])).toThrow()
    expect(() => timestamp('2026-10-23T12:00:00')).toThrow()
    expect(() => positive(0)).toThrow()
  })
})

describe('registered host source receipt', () => {
  const valid = {
    host: 'registered-host',
    model: 'authorized-model',
    skill_digest: 'a'.repeat(64),
    prompt_digest: 'b'.repeat(64),
    authorized_budget_digest: 'c'.repeat(64),
    actual_tool_calls: 5,
  }
  it('decodes explicit host/model and bounded actual tool calls', () => {
    expect(parseHostEvidence(valid)).toEqual(valid)
  })
  it.each([0, 101, 1.5, true])('rejects unproven tool call count %s', (actual_tool_calls) => {
    expect(() => parseHostEvidence({ ...valid, actual_tool_calls })).toThrow()
  })
  it('rejects a missing frozen budget digest', () => {
    expect(() => parseHostEvidence({ ...valid, authorized_budget_digest: undefined })).toThrow()
  })
})

describe('explicit historical seal contract', () => {
  it('rejects a pending verdict claimed as a sealed terminal result', () => {
    expect(() => parseBatch({ ...selfTestBatch, sealed_verdict: 'pending' })).toThrow()
  })
})

describe('assisted revision lineage contract', () => {
  it('preserves real reviewer identities, prior pinned versions and digest-only changes', () => {
    expect(parseAssistedLineage(selfTestAssistedLineage)).toEqual(selfTestAssistedLineage)
  })
  it.each([
    { review_mode: 'automatically_approved' },
    { workflow_reviewer_id: null },
    { authorization_digest: undefined },
    { revision_number: 0 },
    { revision_number: 21 },
    { changes: [] },
    { changes: [selfTestAssistedLineage.changes[0], selfTestAssistedLineage.changes[0]] },
    { changes: [{ ...selfTestAssistedLineage.changes[0], path: '$.auth.token' }] },
    { changes: [{ ...selfTestAssistedLineage.changes[0], after_digest: 'a'.repeat(64) }] },
    { secret_value: 'unapproved-field' },
  ])('rejects an incomplete or fabricated lineage %j', (override) => {
    expect(() => parseAssistedLineage({ ...selfTestAssistedLineage, ...override })).toThrow()
  })
})
