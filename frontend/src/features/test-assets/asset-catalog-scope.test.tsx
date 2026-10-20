import { act, renderHook, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { parseAssetCatalogScope, useAssetCatalogScope } from './asset-catalog-scope'

const environmentId = '00000000-0000-4000-8000-000000000099'

describe('asset catalog URL scope', () => {
  it('parses publication, latest status, environment and each catalog page', () => {
    const result = parseAssetCatalogScope(
      new URLSearchParams(
        `assetPublication=published&assetResult=quarantined&assetEnvironment=${environmentId}&assetOrder=latest_run_desc&casePage=3&suitePage=2`,
      ),
    )
    expect(result.scope).toEqual({
      publication: 'published',
      latest_result: 'quarantined',
      environment_id: environmentId,
      order: 'latest_run_desc',
    })
    expect([result.casePage, result.suitePage]).toEqual([3, 2])
    const params = new URLSearchParams('assetSearch=订单&casePage=3')
    const key = parseAssetCatalogScope(params).selectionKey
    params.set('focus', 'case-one')
    params.set('version', '1')
    expect(parseAssetCatalogScope(params).selectionKey).toBe(key)
  })
  it.each([
    'assetPublication=unknown',
    'assetResult=unknown',
    'assetEnvironment=invalid',
    'assetOrder=unknown',
    'casePage=0',
    'suitePage=NaN',
  ])('rejects an invalid shared scope instead of querying all records: %s', (query) => {
    const result = parseAssetCatalogScope(new URLSearchParams(query))
    expect(result.scope).toBeNull()
    expect(result.error).toBeTruthy()
    expect(Number.isFinite(result.casePage)).toBe(true)
    expect(Number.isFinite(result.suitePage)).toBe(true)
  })
  it('composes batched filter changes, resets pages and preserves focused version', async () => {
    const view = renderHook(
      () => ({ scope: useAssetCatalogScope(), location: useLocation(), navigate: useNavigate() }),
      {
        wrapper: ({ children }) => (
          <MemoryRouter
            initialEntries={['/?folder=folder-one&focus=case-one&version=1&casePage=3&suitePage=4']}
          >
            {children}
          </MemoryRouter>
        ),
      },
    )
    act(() => {
      view.result.current.scope.setFilter('search', '订单')
      view.result.current.scope.setFilter('tag', 'smoke')
    })
    await waitFor(() =>
      expect(view.result.current.scope.filters).toMatchObject({ search: '订单', tag: 'smoke' }),
    )
    expect([view.result.current.scope.casePage, view.result.current.scope.suitePage]).toEqual([
      1, 1,
    ])
    expect(view.result.current.location.search).toContain('focus=case-one')
    expect(view.result.current.location.search).toContain('version=1')
    act(() => {
      view.result.current.scope.setPage('case', 2)
      view.result.current.scope.setPage('suite', 3)
    })
    await waitFor(() =>
      expect([view.result.current.scope.casePage, view.result.current.scope.suitePage]).toEqual([
        2, 3,
      ]),
    )
    act(() => view.result.current.scope.setFilter('publication', 'published'))
    await waitFor(() => expect(view.result.current.scope.filters.publication).toBe('published'))
    act(() => view.result.current.navigate(-1))
    await waitFor(() => expect(view.result.current.scope.filters.publication).toBe(''))
    expect([view.result.current.scope.casePage, view.result.current.scope.suitePage]).toEqual([
      2, 3,
    ])
  })
})
