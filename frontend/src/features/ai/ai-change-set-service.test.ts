import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/server'
import {
  createAIChangeSet,
  getAIChangeSet,
  listAIChangeSets,
  reviewAIChangeItem,
} from './ai-change-set-service'

describe('AI change receipts', () => {
  it('rejects a foreign catalog and a different detail identity', async () => {
    server.use(
      http.get('/api/v1/ai/change-sets', () =>
        HttpResponse.json({ items: [{ id: 'other', project_id: 'foreign' }], total: 1 }),
      ),
      http.get('/api/v1/ai/change-sets/requested', () => HttpResponse.json({ id: 'other' })),
    )
    await expect(listAIChangeSets('owned')).rejects.toThrow('其他项目')
    await expect(getAIChangeSet('requested')).rejects.toThrow('与请求不一致')
  })
  it('rejects an unrelated create receipt', async () => {
    server.use(
      http.post('/api/v1/ai/change-sets', () =>
        HttpResponse.json({ id: 'new', project_id: 'foreign' }),
      ),
    )
    await expect(
      createAIChangeSet({
        project_id: 'owned',
        impact_run_id: 'impact',
        release_risk_id: 'risk',
        title: '隔离',
      }),
    ).rejects.toThrow('不属于当前项目')
  })
  it.each([
    { id: 'other', review_status: 'accepted' },
    { id: 'item', review_status: 'pending' },
  ])('does not accept a mismatched review acknowledgment %#', async (receipt) => {
    let writes = 0
    server.use(
      http.post('/api/v1/ai/change-sets/set/items/item/accept', () => {
        writes++
        return HttpResponse.json(receipt)
      }),
    )
    await expect(reviewAIChangeItem('set', 'item', 'accept', { note: '人工核验' })).rejects.toThrow(
      '与请求不一致',
    )
    expect(writes).toBe(1)
  })
})
