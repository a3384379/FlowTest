import { describe, expect, it } from 'vitest'
import { contractServiceLocation, contractServicePath } from './contract-service-location'

const id = '01234567-abcd-4000-8000-000000000001'
describe('contract service navigation identity', () => {
  it.each([
    `contractServiceId=${id}`,
    `focus=contract_service:${id}`,
    `contractServiceId=${id.toUpperCase()}`,
  ])('resolves canonical and legacy %s', (query) => {
    expect(contractServiceLocation(new URLSearchParams(query))).toEqual({ id, error: null })
  })
  it('consumes the old impact parameter only in its known context', () => {
    expect(contractServiceLocation(new URLSearchParams(`service_id=${id}`)).id).toBeNull()
    expect(contractServiceLocation(new URLSearchParams(`service_id=${id}`), true).id).toBe(id)
  })
  it.each(['', 'not-an-id', 'a/b'])('rejects malformed explicit identity %s', (value) => {
    expect(
      contractServiceLocation(new URLSearchParams({ contractServiceId: value })).error,
    ).toBeTruthy()
  })
  it('keeps an explicit invalid locator from falling back to another legacy object', () => {
    expect(
      contractServiceLocation(
        new URLSearchParams({ contractServiceId: 'invalid', focus: `contract_service:${id}` }),
      ).error,
    ).toBeTruthy()
    expect(contractServicePath('project-a', 'contracts', id)).toBe(
      `/projects/project-a/contracts?contractServiceId=${id}`,
    )
  })
})
