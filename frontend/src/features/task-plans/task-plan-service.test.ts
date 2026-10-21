import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { project, workflow } from '../../test/fixtures'
import { server } from '../../test/server'
import { createTestPlan, getTestPlan, type CreateTestPlanInput } from './task-plan-service'

function planInput(count: number): CreateTestPlanInput {
  return {
    name: '固定多目标计划',
    intervalSeconds: null,
    cronExpression: null,
    timezone: 'Asia/Shanghai',
    priority: 5,
    items: Array.from({ length: count }, (_, index) => ({
      targetType: 'workflow',
      targetId: workflow.id,
      targetVersion: index + 1,
      environmentId: 'owned-environment',
      maxRetries: 0,
    })),
  }
}

describe('task plan client boundaries', () => {
  it('preserves one hundred ordered pinned items and rejects an extra item without a request', async () => {
    const payloads: Array<{ items: Array<{ target_version: number }> }> = []
    server.use(
      http.post(`/api/v1/projects/${project.id}/test-plans`, async ({ request }) => {
        payloads.push((await request.json()) as (typeof payloads)[number])
        return HttpResponse.json({ id: 'new-plan' }, { status: 201 })
      }),
    )
    await createTestPlan(project.id, planInput(100))
    expect(payloads[0].items.map((item) => item.target_version)).toEqual(
      Array.from({ length: 100 }, (_, i) => i + 1),
    )
    await expect(createTestPlan(project.id, planInput(101))).rejects.toThrow('1至100个执行项')
    await expect(createTestPlan(project.id, planInput(0))).rejects.toThrow('1至100个执行项')
    expect(payloads).toHaveLength(1)
  })

  it('rejects an unpublished version before sending any plan creation', async () => {
    let requests = 0
    server.use(
      http.post(`/api/v1/projects/${project.id}/test-plans`, () => {
        requests++
        return HttpResponse.json({})
      }),
    )
    const input = planInput(1)
    input.items[0].targetVersion = 0
    await expect(createTestPlan(project.id, input)).rejects.toThrow('已发布的固定版本')
    expect(requests).toBe(0)
  })

  it('rejects an exact-ID read whose response belongs to another project', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/test-plans/owned-id`, () =>
        HttpResponse.json({ id: 'owned-id', project_id: 'foreign-project' }),
      ),
    )
    await expect(getTestPlan(project.id, 'owned-id')).rejects.toThrow('不属于当前项目或计划')
  })
})
