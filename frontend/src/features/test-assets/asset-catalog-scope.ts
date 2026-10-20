import { useLayoutEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

export type AssetCatalogScope = {
  publication?: 'published' | 'unpublished'
  latest_result?: 'unrun' | 'queued' | 'running' | 'passed' | 'failed' | 'cancelled' | 'quarantined'
  environment_id?: string
  order: 'updated_desc' | 'name_asc' | 'name_desc' | 'latest_run_desc'
}
export type AssetFilterKey = 'search' | 'tag' | 'publication' | 'result' | 'environment' | 'order'
type Fields = Record<AssetFilterKey, string>
const names: Record<AssetFilterKey, string> = {
  search: 'assetSearch',
  tag: 'assetTag',
  publication: 'assetPublication',
  result: 'assetResult',
  environment: 'assetEnvironment',
  order: 'assetOrder',
}

export function parseAssetCatalogScope(params: URLSearchParams) {
  const filters = Object.fromEntries(
    Object.entries(names).map(([key, name]) => [key, params.get(name) ?? '']),
  ) as Fields
  if (!filters.order) filters.order = 'updated_desc'
  const error = fieldError(filters) || pageError(params)
  const scope: AssetCatalogScope | null = error ? null : requestScope(filters)
  return {
    filters,
    scope,
    error,
    casePage: validPage(params, 'casePage'),
    suitePage: validPage(params, 'suitePage'),
    selectionKey: JSON.stringify(filters),
  }
}

function requestScope(fields: Fields): AssetCatalogScope {
  return {
    publication: (fields.publication || undefined) as AssetCatalogScope['publication'],
    latest_result: (fields.result || undefined) as AssetCatalogScope['latest_result'],
    environment_id: fields.environment || undefined,
    order: fields.order as AssetCatalogScope['order'],
  }
}

function choiceError(value: string, supported: readonly string[], label: string) {
  return value && !supported.includes(value) ? `URL 中的${label}无效` : null
}
function fieldError(fields: Fields): string | null {
  return (
    choiceError(fields.publication, ['published', 'unpublished'], '发布状态') ||
    choiceError(
      fields.result,
      ['unrun', 'queued', 'running', 'passed', 'failed', 'cancelled', 'quarantined'],
      '最近结果',
    ) ||
    choiceError(
      fields.order,
      ['updated_desc', 'name_asc', 'name_desc', 'latest_run_desc'],
      '排序方式',
    ) ||
    environmentError(fields.environment) ||
    lengthError(fields)
  )
}
function environmentError(value: string) {
  return value && !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
    ? 'URL 中的运行环境 ID 无效'
    : null
}
function lengthError(fields: Fields) {
  return fields.search.length > 200 || fields.tag.length > 50 ? '搜索词或标签超过允许长度' : null
}
function validPage(params: URLSearchParams, key: string) {
  const value = Number(params.get(key) ?? 1)
  return Number.isSafeInteger(value) && value > 0 ? value : 1
}

function pageError(params: URLSearchParams) {
  const invalid = ['casePage', 'suitePage'].some((key) => {
    const value = Number(params.get(key) ?? 1)
    return !Number.isSafeInteger(value) || value < 1
  })
  return invalid ? 'URL 中的目录页码无效' : null
}

export function useAssetCatalogScope() {
  const [params, setParams] = useSearchParams()
  const pending = useRef(params)
  useLayoutEffect(() => {
    pending.current = params
  }, [params])
  function write(update: (next: URLSearchParams) => void) {
    const next = new URLSearchParams(pending.current)
    update(next)
    pending.current = next
    setParams(next)
  }
  const state = parseAssetCatalogScope(params)
  return {
    ...state,
    setFilter: (key: AssetFilterKey, value: string) => {
      write((next) => {
        if (value) next.set(names[key], value)
        else next.delete(names[key])
        next.delete('casePage')
        next.delete('suitePage')
      })
    },
    setPage: (kind: 'case' | 'suite', page: number) => {
      write((next) => {
        next.set(kind === 'case' ? 'casePage' : 'suitePage', String(page))
      })
    },
    resetPages: () => {
      write((next) => {
        next.delete('casePage')
        next.delete('suitePage')
      })
    },
    reset: () => {
      write((next) => {
        Object.values(names).forEach((key) => next.delete(key))
        next.delete('casePage')
        next.delete('suitePage')
      })
    },
  }
}
