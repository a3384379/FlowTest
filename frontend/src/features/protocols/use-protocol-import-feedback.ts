import { App } from 'antd'
import { useLayoutEffect, useRef } from 'react'
import { apiErrorWithTrace } from '../../lib/api'

export function useProtocolImportFeedback(allowed: boolean) {
  const { message } = App.useApp()
  const active = useRef(false)
  const permitted = useRef(allowed)
  useLayoutEffect(() => {
    permitted.current = allowed
  }, [allowed])
  useLayoutEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  return {
    allowed: () => active.current && permitted.current,
    success: (text: string) => {
      if (active.current && permitted.current) void message.success(text)
    },
    error: (error: Error) => {
      if (active.current && permitted.current) void message.error(apiErrorWithTrace(error))
    },
  }
}
