import { describe, expect, it } from 'vitest'

import { linearWorkflow } from './workflow-service'
import { buildWorkflowTemplate, WORKFLOW_TEMPLATES } from './workflow-templates'

const API_ID = '00000000-0000-0000-0000-000000000001'
const SUBMIT_ID = '00000000-0000-0000-0000-000000000002'

describe('workflow creation templates', () => {
  it.each(WORKFLOW_TEMPLATES)('builds $value as a connected draft', ({ value }) => {
    const definition = buildWorkflowTemplate(linearWorkflow(API_ID, 2), value, {
      submitApiId: SUBMIT_ID,
      submitApiVersion: 3,
    })
    const mainIds = new Set(definition.nodes.map((node) => node.id))
    expect(
      definition.edges.every((edge) => mainIds.has(edge.source) && mainIds.has(edge.target)),
    ).toBe(true)
    expect(definition.edges).toHaveLength(value === 'async_poll' ? 3 : 2)
    expect(definition.nodes).toHaveLength(value === 'async_poll' ? 4 : 3)
    expect(definition.nodes.find((node) => node.id === 'start')).toBeDefined()
    expect(definition.nodes.find((node) => node.id === 'end')).toBeDefined()
    if (value === 'linear' || value === 'async_poll') {
      expect(definition.schema_version).toBe('1.0')
      expect(definition.regions).toBeUndefined()
      return
    }
    expect(definition.schema_version).toBe('4.0')
    expect(definition.run_policy?.request_budget).toBe(1000)
    const owner = definition.nodes.find((node) => node.type === 'capability')!
    expect(definition.regions?.every((region) => region.owner_node_id === owner.id)).toBe(true)
    expect(definition.edges[0].target).toBe(owner.id)
    expect(definition.edges[1].source).toBe(owner.id)
  })

  it('uses distinct nodes for the two parallel branches', () => {
    const definition = buildWorkflowTemplate(linearWorkflow(API_ID, 2), 'parallel_compare')
    const regions = definition.regions!
    expect(regions.map((region) => region.nodes[0].id)).toEqual(['api-first', 'api-second'])
    expect(regions.every((region) => region.nodes[0].config.api_version === 2)).toBe(true)
  })

  it('binds a bounded pagination state to the API query parameter', () => {
    const definition = buildWorkflowTemplate(linearWorkflow(API_ID, 2), 'pagination')
    const loop = definition.nodes.find((node) => node.type === 'capability')!
    expect(loop.configuration?.state).toEqual({ page: { kind: 'literal', value: 1 } })
    expect(loop.configuration?.policy).toMatchObject({ max_iterations: 3 })
    expect(definition.regions?.[0].nodes[0].config.request_overrides).toEqual({
      query_parameters: [{ name: 'page', value: '{{state.page}}', enabled: true }],
    })
  })

  it('advances cursor and stop state from the current page output', () => {
    const definition = buildWorkflowTemplate(linearWorkflow(API_ID, 2), 'cursor_pagination')
    const loop = definition.nodes.find((node) => node.type === 'capability')!
    expect(loop.configuration?.state).toEqual({
      cursor: { kind: 'literal', value: '' },
      hasNext: { kind: 'literal', value: true },
    })
    expect(loop.configuration?.update).toEqual({
      cursor: {
        kind: 'set',
        value: { kind: 'node_output', node_id: 'api', path: ['body', 'nextCursor'] },
      },
      hasNext: {
        kind: 'set',
        value: { kind: 'node_output', node_id: 'api', path: ['body', 'hasNext'] },
      },
    })
    expect(loop.configuration?.policy).toMatchObject({ max_iterations: 100, timeout_seconds: 120 })
    expect(definition.regions?.[0].nodes[0].config.request_overrides).toEqual({
      query_parameters: [{ name: 'cursor', value: '{{state.cursor}}', enabled: true }],
    })
  })

  it('keeps polling separate from failure retries', () => {
    const definition = buildWorkflowTemplate(linearWorkflow(API_ID, 2), 'async_poll', {
      submitApiId: SUBMIT_ID,
      submitApiVersion: 3,
    })
    const submit = definition.nodes.find((node) => node.id === 'submit')!
    const request = definition.nodes.find((node) => node.id === 'api')!
    expect(submit.config).toMatchObject({
      api_definition_id: SUBMIT_ID,
      api_version: 3,
      max_retries: 0,
    })
    expect(request.config.max_retries).toBe(0)
    expect(request.config.polling).toMatchObject({
      max_attempts: 20,
      expected: 'SUCCESS',
      terminal_failure_values: ['FAILED'],
    })
    expect(definition.edges[1].mappings).toEqual([
      {
        source: { node_id: 'submit', path: 'body.taskId' },
        transform: { kind: 'identity', template: '{{value}}' },
        target: { node_id: 'api', location: 'query', key: 'taskId' },
      },
    ])
    expect(() => buildWorkflowTemplate(linearWorkflow(API_ID, 2), 'async_poll')).toThrow()
  })

  it('passes each ForEach item to its API request', () => {
    const definition = buildWorkflowTemplate(linearWorkflow(API_ID, 2), 'foreach_three')
    expect(definition.regions?.[0].nodes[0].config.request_overrides).toEqual({
      query_parameters: [{ name: 'item', value: '{{loop.item}}', enabled: true }],
    })
  })
})
