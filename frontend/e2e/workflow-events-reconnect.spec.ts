import { expect, test } from '@playwright/test'

import { seedEditor } from './support/workflow-editor'

test('执行事件断线后按序号重连并从持久化结果恢复终态', async ({ page }) => {
  await page.addInitScript(() => {
    type TrackedSocket = { socket: WebSocket; url: string; sequences: number[] }
    const target = window as unknown as { __flowtestEventSockets: TrackedSocket[] }
    target.__flowtestEventSockets = []
    const NativeWebSocket = window.WebSocket
    window.WebSocket = class extends NativeWebSocket {
      constructor(url: string | URL, protocols?: string | string[]) {
        super(url, protocols)
        if (!String(url).includes('/executions/')) return
        const entry: TrackedSocket = { socket: this, url: String(url), sequences: [] }
        target.__flowtestEventSockets.push(entry)
        this.addEventListener('message', (message) => {
          const match = /"sequence":(\d+)/.exec(String(message.data))
          if (match) entry.sequences.push(Number(match[1]))
        })
      }
    }
  })

  await seedEditor(page, (definition) => ({
    ...definition,
    nodes: definition.nodes.map((node) =>
      node.id === 'api'
        ? { ...node, type: 'delay' as const, name: '等待重连', config: { seconds: 5 } }
        : node,
    ),
  }))
  await page.getByRole('button', { name: '工作流更多操作' }).click()
  await page.getByRole('button', { name: 'cloud-upload 发布服务器草稿' }).click()
  await page
    .getByRole('dialog', { name: '发布服务器草稿？' })
    .getByRole('button', { name: '发布服务器草稿' })
    .click()
  const started = page.waitForResponse(
    (response) =>
      /\/workflows\/[^/]+\/executions$/.test(response.url()) &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '运行已发布版本' }).click()
  expect((await started).ok()).toBeTruthy()

  await expect
    .poll(() =>
      page.evaluate(() => {
        const target = window as unknown as {
          __flowtestEventSockets: Array<{ sequences: number[] }>
        }
        return target.__flowtestEventSockets[0]?.sequences.length ?? 0
      }),
    )
    .toBeGreaterThan(0)
  const cursor = await page.evaluate(() => {
    const target = window as unknown as {
      __flowtestEventSockets: Array<{ socket: WebSocket; sequences: number[] }>
    }
    const first = target.__flowtestEventSockets[0]
    const latest = first.sequences.at(-1) ?? 0
    first.socket.close(4001, 'test-disconnect')
    return latest
  })
  await expect
    .poll(() =>
      page.evaluate(() => {
        const target = window as unknown as {
          __flowtestEventSockets: Array<{ url: string }>
        }
        return target.__flowtestEventSockets[1]?.url ?? ''
      }),
    )
    .toContain(`after_sequence=${cursor}`)
  await expect
    .poll(() =>
      page.evaluate(() => {
        const target = window as unknown as {
          __flowtestEventSockets: Array<{ sequences: number[] }>
        }
        return target.__flowtestEventSockets[1]?.sequences ?? []
      }),
    )
    .not.toEqual([])
  const replayed = await page.evaluate(() => {
    const target = window as unknown as {
      __flowtestEventSockets: Array<{ sequences: number[] }>
    }
    return target.__flowtestEventSockets[1].sequences
  })
  expect(replayed.every((sequence) => sequence > cursor)).toBeTruthy()
  await expect(page.getByText('工作流执行通过').last()).toBeVisible({ timeout: 30_000 })
})
