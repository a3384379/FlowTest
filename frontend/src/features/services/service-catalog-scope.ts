import { useSearchParams } from 'react-router-dom'
import { contractServiceLocation } from './contract-service-location'

export function useServiceCatalogScope() {
  const [params, setParams] = useSearchParams()
  const search = params.get('serviceSearch') ?? ''
  const requestedPage = Number(params.get('servicePage') ?? 1)
  const page = Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1
  const selection = contractServiceLocation(params)
  const scopeError =
    search.length > 200 || !Number.isSafeInteger(requestedPage) || requestedPage < 1
      ? 'URL 中的服务搜索范围或页码无效'
      : null
  function selectService(id: string | null) {
    const next = new URLSearchParams(params)
    next.delete('focus')
    if (id) next.set('contractServiceId', id)
    else next.delete('contractServiceId')
    setParams(next)
  }
  return {
    search,
    page,
    scopeError,
    selection,
    selectService,
    setSearch: (value: string) => {
      const next = new URLSearchParams(params)
      next.set('serviceSearch', value.trim())
      next.delete('servicePage')
      setParams(next)
    },
    setPage: (value: number) => {
      const next = new URLSearchParams(params)
      next.set('servicePage', String(value))
      setParams(next)
    },
    resetScope: () => {
      const next = new URLSearchParams(params)
      next.delete('serviceSearch')
      next.delete('servicePage')
      setParams(next)
    },
  }
}
