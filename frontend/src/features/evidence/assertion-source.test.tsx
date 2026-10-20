import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import AssertionEvidence from './AssertionEvidence'
import { reportAssertionEvidence, workflowAssertionEvidence } from './assertion-model'
import {
  definitionAssertionProvenance,
  locateAssertionSource,
  type AssertionSourceContext,
} from './assertion-source'
import { workflowDefinition } from '../../test/fixtures'

const context: AssertionSourceContext = {
  projectId: 'project-frozen',
  executionId: 'run-frozen',
  assertionNodeId: 'assert',
  nodes: [
    {
      node_id: 'api',
      name: '订单响应',
      status: 'passed',
      attempts: 3,
      result: { observations: [{ attempt: 1 }, { attempt: 3 }] },
    },
    { node_id: 'expected', name: '期望数据', status: 'passed', attempts: 1 },
  ],
}
const output = {
  passed: false,
  actual: 29901,
  expected: 29900,
  source_node_id: 'api',
  expression: 'body.items[0].amount',
  operator: 'equals',
  expected_source_node_id: 'expected',
  expected_expression: 'body.expected',
}

describe('frozen assertion provenance', () => {
  it('locates actual and dynamic expected sources within the same frozen execution', () => {
    render(
      <MemoryRouter>
        <AssertionEvidence items={reportAssertionEvidence(output, '订单金额')} location={context} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /订单响应/ })).toHaveAttribute(
      'href',
      '/projects/project-frozen/reports?execution=run-frozen&node=api&attempt=3',
    )
    expect(screen.getByRole('link', { name: /期望数据/ })).toHaveAttribute(
      'href',
      '/projects/project-frozen/reports?execution=run-frozen&node=expected&attempt=1',
    )
    expect(
      screen.getAllByText('body.items[0].amount', { selector: 'code', exact: true }),
    ).toHaveLength(2)
    expect(screen.getByText('body.expected', { selector: 'code', exact: true })).toBeVisible()
    expect(screen.getByText('差值（实际 − 期望）：+1 · 单位：未提供')).toBeVisible()
  })
  it('keeps missing sources and region instances unresolved rather than linking another iteration', () => {
    const instance = { ...context, instanceId: '__nested_request__:item-2-attempt-1' }
    render(
      <MemoryRouter>
        <AssertionEvidence
          items={reportAssertionEvidence(output, '循环金额')}
          location={instance}
        />
      </MemoryRouter>,
    )
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getAllByText(/区域实例的来源轮次未解析/)).toHaveLength(2)
    expect(
      locateAssertionSource({ nodeId: 'missing', expression: 'body.id' }, context),
    ).toMatchObject({ reason: '同次运行未提供来源节点证据' })
    expect(
      locateAssertionSource(
        { nodeId: 'api', expression: 'body.id' },
        { ...context, nodes: [{ ...context.nodes[0], status: 'failed' }] },
      ),
    ).toMatchObject({ reason: '来源节点未成功完成，无法确认对应尝试' })
  })
  it('reads definitions only from the explicit frozen snapshot and preserves recorded expectations', () => {
    const frozen = structuredClone(workflowDefinition)
    frozen.nodes.push({
      ...frozen.nodes[1],
      id: 'assert',
      type: 'assert',
      config: {
        source_node_id: 'api',
        expression: 'body.amount',
        operator: 'equals',
        expected: 29900,
      },
    })
    const draft = structuredClone(frozen)
    draft.nodes.find((node) => node.id === 'assert')!.config = {
      source_node_id: 'expected',
      expression: 'new.body',
      expected: 0,
    }
    const evidence = [{ name: '金额', passed: false, expected: 29900, actual: 29901 }]
    render(
      <MemoryRouter>
        <AssertionEvidence items={evidence} location={{ ...context, frozenDefinition: frozen }} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /订单响应/ })).toBeVisible()
    expect(screen.getAllByText('body.amount', { selector: 'code' })).toHaveLength(2)
    expect(screen.getByText('29900')).toBeVisible()
    expect(screen.queryByText('new.body')).not.toBeInTheDocument()
    expect(
      definitionAssertionProvenance({ ...context, frozenDefinition: undefined }),
    ).toBeUndefined()
  })
  it('does not borrow provenance from conflicting output or assume an incomplete dynamic source is literal', () => {
    const standard = { name: '另一条断言', passed: true, actual: 0, expected: 0 }
    expect(
      workflowAssertionEvidence({
        node_type: 'assert',
        name: '断言',
        output,
        result: { assertions: [standard] },
      })[0].provenance,
    ).toBeUndefined()
    render(
      <MemoryRouter>
        <AssertionEvidence
          items={reportAssertionEvidence({ ...output, expected_expression: undefined }, '金额')}
          location={context}
        />
      </MemoryRouter>,
    )
    expect(screen.getByText('期望值来源：未解析（冻结来源字段不完整）')).toBeVisible()
    expect(screen.queryByText('期望值来源：当次断言记录的固定值')).not.toBeInTheDocument()
  })
})
