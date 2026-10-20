import { App } from 'antd'
import { useLayoutEffect, useRef, useState } from 'react'
import { apiErrorWithTrace } from '../../lib/api'

export function useProtocolDebugResult<T>() {
  const { message } = App.useApp()
  const active = useRef(true)
  const generation = useRef(0)
  const [result, setResult] = useState<T | null>(null)
  useLayoutEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  function begin() {
    setResult(null)
    return ++generation.current
  }
  function accept(value: T, revision: number | undefined) {
    if (active.current && revision === generation.current) setResult(value)
  }
  function fail(error: unknown, revision: number | undefined) {
    if (active.current && revision === generation.current)
      void message.error(apiErrorWithTrace(error))
  }
  return { result, begin, invalidate: begin, accept, fail }
}
