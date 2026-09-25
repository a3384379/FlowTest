import { expect, test } from '@playwright/test'

import { seedEditor } from './support/workflow-editor'

test('区域画布删除线性步骤后保存并重载仍保留安全连线', async ({ page }) => {
  const fixture = await seedEditor(page, (definition) => ({
    ...definition,
    schema_version: '4.0',
    run_policy: {
      request_budget: 20,
      max_runtime_seconds: 60,
      cleanup_request_budget: null,
      force_cancel_skips_cleanup: true,
    },
    nodes: [
      definition.nodes[0],
      {
        id: 'group',
        type: 'capability',
        name: '三步区域',
        position: { x: 260, y: 80 },
        config: {},
        capability_id: 'flow.control.group',
        capability_version: '1.0.0',
        configuration: { body: { kind: 'inline', region_id: 'region' }, inputs: {} },
        bindings: [],
      },
      definition.nodes[2],
    ],
    edges: [
      { id: 'start-group', source: 'start', target: 'group', condition: null, mappings: [] },
      { id: 'group-end', source: 'group', target: 'end', condition: null, mappings: [] },
    ],
    regions: [
      {
        id: 'region',
        owner_node_id: 'group',
        role: 'body',
        nodes: ['first', 'middle', 'last'].map((id, index) => ({
          id,
          type: 'delay' as const,
          name: `等待 ${index + 1}`,
          position: { x: index * 220, y: 0 },
          config: { seconds: 0 },
        })),
        edges: [
          { id: 'first-middle', source: 'first', target: 'middle', condition: null, mappings: [] },
          { id: 'middle-last', source: 'middle', target: 'last', condition: null, mappings: [] },
        ],
        entry_node_id: 'first',
        exit_node_ids: ['last'],
        inputs: {},
        outputs: {},
      },
    ],
  }))

  await page.locator('.react-flow__node[data-id=group]').click()
  await page.getByRole('button', { name: '打开区域画布' }).click()
  const dialog = page.getByRole('dialog', { name: 'body 区域画布' })
  await dialog.locator('.react-flow__node[data-id=middle]').click()
  await dialog.getByRole('button', { name: '删除所选步骤' }).click()
  await page.getByRole('button', { name: /确\s*定|OK/ }).click()
  await expect(dialog.locator('.react-flow__node')).toHaveCount(2)
  await expect(dialog.locator('.react-flow__edge[data-id=first-middle]')).toHaveCount(1)
  await dialog.locator('.ant-modal-close').click()
  await page.getByRole('button', { name: '保存草稿' }).click()
  await expect(page.getByText('草稿已保存').last()).toBeVisible()
  await page.reload()
  await page.locator('.react-flow__node[data-id=group]').click()
  await page.getByRole('button', { name: '打开区域画布' }).click()
  const reopened = page.getByRole('dialog', { name: 'body 区域画布' })
  await expect(reopened.locator('.react-flow__node')).toHaveCount(2)
  const response = await page.request.get(
    `/api/v1${fixture.root}/workflows/${fixture.workflow.id}`,
    {
      headers: fixture.headers,
    },
  )
  expect(response.ok()).toBeTruthy()
  const saved = (await response.json()) as {
    draft_definition: { regions: Array<{ edges: unknown[] }> }
  }
  expect(saved.draft_definition.regions[0].edges).toHaveLength(1)
})
