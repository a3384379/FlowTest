import type { FormInstance } from 'antd'
import axios from 'axios'
import { useLayoutEffect, useRef, useState } from 'react'
import { apiErrorWithTrace } from '../../lib/api'
import type { MockPreviewResult } from './data-source-service'
import type { MockRouteFields } from './mock-form-values'

export function useMockPreviewState(sourceKey: string) {
  const generation = useRef(0)
  const active = useRef(true)
  const [result, setResult] = useState<MockPreviewResult | null>(null)
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const [previousSource, setPreviousSource] = useState(sourceKey)
  if (previousSource !== sourceKey) {
    setPreviousSource(sourceKey)
    setResult(null)
    setError('')
    setPending(false)
  }
  useLayoutEffect(() => {
    active.current = true
    return () => {
      active.current = false
      generation.current += 1
    }
  }, [])
  useLayoutEffect(() => {
    generation.current += 1
  }, [sourceKey])
  function start() {
    const currentGeneration = ++generation.current
    setResult(null)
    setError('')
    setPending(true)
    return () => active.current && generation.current === currentGeneration
  }
  function invalidate() {
    generation.current += 1
    setResult(null)
    setError('')
    setPending(false)
  }
  return { start, result, setResult, error, setError, pending, setPending, invalidate }
}

export function applyPreviewError(
  error: unknown,
  routeId: string | null,
  form: FormInstance<MockRouteFields>,
  setError: (value: string) => void,
) {
  if (!axios.isAxiosError(error)) return
  const location = previewErrorLocation(error.response?.data?.error?.details)
  const message = apiErrorWithTrace(error) + location.text
  setError(message)
  if (location.field && location.routeId === routeId)
    form.setFields([{ name: location.field, errors: [message] }])
}

type PreviewField =
  'response_body' | 'path_pattern' | 'query_conditions' | 'header_conditions' | 'response_headers'
function previewErrorLocation(details: unknown): {
  field?: PreviewField
  text: string
  routeId: string | null
} {
  if (!details || typeof details !== 'object') return { text: '', routeId: null }
  const value = details as { field?: unknown; pointer?: unknown; route_id?: unknown }
  const known = [
    'response_body',
    'path_pattern',
    'query_conditions',
    'header_conditions',
    'response_headers',
  ]
  const field =
    typeof value.field === 'string' && known.includes(value.field)
      ? (value.field as PreviewField)
      : undefined
  const pointer = typeof value.pointer === 'string' ? value.pointer : ''
  return {
    field,
    text: typeof value.field === 'string' ? `；字段 ${value.field}${pointer || '（根值）'}` : '',
    routeId: typeof value.route_id === 'string' ? value.route_id : null,
  }
}
