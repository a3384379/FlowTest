import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import WorkflowDesigner from './WorkflowDesigner'
import { apiDefinition, workflowDefinition } from '../test/fixtures'
import type { WorkflowDefinition } from '../lib/api'

it('DEL02/03/08 confirms mapped deletion, preserves cancellation, and rejects stale approval', async () => {
  const change = vi.fn()
  const definition: WorkflowDefinition = {
    ...workflowDefinition,
    edges: workflowDefinition.edges.map((edge, index) =>
      index === 0
        ? {
            ...edge,
            mappings: [
              {
                source: { node_id: 'start', path: 'variables.id' },
                target: { node_id: 'api', location: 'query', key: 'id' },
                transform: { kind: 'json_parse', template: '{{value}}' },
              },
            ],
          }
        : edge,
    ),
  }
  const tree = (value: WorkflowDefinition) => (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <WorkflowDesigner
        definition={value}
        apis={[apiDefinition]}
        artifacts={[]}
        credentials={[]}
        statuses={{}}
        editable
        onChange={change}
      />
    </ConfigProvider>
  )
  const view = render(tree(definition))
  const user = userEvent.setup()
  fireEvent.click(screen.getByTestId('rf__node-api'))
  await user.click(screen.getByRole('button', { name: /删除节点/ }))
  const dialog = await screen.findByRole('dialog', { hidden: true })
  expect(dialog).toHaveTextContent('1 条字段映射')
  await user.click(within(dialog).getByRole('button', { name: /取\s*消/ }))
  expect(change).not.toHaveBeenCalled()
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { hidden: true })).not.toBeInTheDocument(),
  )
  await user.click(screen.getByRole('button', { name: /删除节点/ }))
  const next = { ...definition, variables: { external: 'new value' } }
  view.rerender(tree(next))
  await user.click(
    within(await screen.findByRole('dialog', { hidden: true })).getByRole('button', {
      name: '确认删除',
    }),
  )
  expect(change).not.toHaveBeenCalled()
  expect(screen.getByTestId('rf__node-api')).toBeInTheDocument()
})
