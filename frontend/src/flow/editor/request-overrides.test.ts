import { describe, expect, it } from 'vitest'
import {
  applyOwnedRequestSections,
  extraRequestPolicies,
  applyRequestEditorDraft,
  requestIdentityMatches,
} from './request-overrides'
import { jsonEqual } from './editor-types'
import { toBodyFields } from '../../features/api-console/body-edit'
import { workflowDefinition } from '../../test/fixtures'
import type { WorkflowRequestEditorDraft } from './node-edit-session'
describe('request section ownership', () => {
  it('keeps absent, empty, null, and explicit override semantics separate', () => {
    const original = {
      query_parameters: [{ name: 'old', value: '1', enabled: true }],
      headers: { Authorization: 'managed' },
      body: { kind: 'json', value: { old: true } },
      auth_disabled: true,
      suppressed_cookies: ['sid'],
    }
    const next = applyOwnedRequestSections(original, {
      params: { mode: 'custom', value: [] },
      headers: { mode: 'custom', value: {} },
      body: { mode: 'custom', value: { kind: 'json', value: null } },
    })
    expect(next).toMatchObject({
      query_parameters: [],
      headers: {},
      body: { kind: 'json', value: null },
      auth_disabled: true,
    })
    expect(original.body.value).toEqual({ old: true })
    const inherited = applyOwnedRequestSections(next, {
      params: { mode: 'inherit' },
      headers: { mode: 'inherit' },
      body: { mode: 'inherit' },
    })
    expect(inherited).toEqual({ auth_disabled: true, suppressed_cookies: ['sid'] })
    expect(extraRequestPolicies(inherited)).toEqual(['auth_disabled', 'suppressed_cookies'])
    expect(extraRequestPolicies(null)).toEqual([])
    expect(
      applyOwnedRequestSections(undefined, {
        params: { mode: 'inherit' },
        headers: { mode: 'inherit' },
        body: { mode: 'inherit' },
      }),
    ).toEqual({})
  })
  it('compares parent echoes semantically without confusing arrays, nulls, or removed keys', () => {
    expect(jsonEqual({ a: 1, b: undefined }, { a: 1 })).toBe(true)
    expect(jsonEqual([1, 2], { '0': 1, '1': 2 })).toBe(false)
    expect(jsonEqual(null, {})).toBe(false)
    expect(jsonEqual({ a: 1 }, { b: 1 })).toBe(false)
    expect(jsonEqual({ a: 1, b: 2 }, { b: 2, a: 1 })).toBe(true)
  })
  it('rejects stale project, node, API, and version identities before patching any fields', () => {
    const node = {
      ...workflowDefinition.nodes[1],
      config: {
        api_definition_id: 'api-A',
        api_version: 12,
        request_overrides: { auth_disabled: true },
      },
    }
    const identity = {
      projectId: 'project-A',
      nodeId: node.id,
      apiDefinitionId: 'api-A',
      apiVersion: 12,
    }
    expect(requestIdentityMatches(node, identity, 'project-B')).toBe(false)
    const draft: WorkflowRequestEditorDraft = {
      identity,
      fields: {
        ...toBodyFields({ body_kind: 'json', body: { edited: true }, headers: {} }),
        headers: [],
        query_parameters: [],
      },
      modes: { params: 'inherit', headers: 'inherit', body: 'custom' },
      customDrafts: {},
      activeTab: 'body',
    }
    for (const stale of [
      { ...identity, nodeId: 'other' },
      { ...identity, apiDefinitionId: 'api-B' },
      { ...identity, apiVersion: 2 },
    ]) {
      expect(() => applyRequestEditorDraft(node, { ...draft, identity: stale })).toThrow(
        '请求目标已变更',
      )
    }
    expect(node.config.request_overrides).toEqual({ auth_disabled: true })
    const unpinned = { ...node, config: { api_definition_id: 'api-A' } }
    expect(applyRequestEditorDraft(unpinned, draft).config.api_version).toBe(12)
  })
})
