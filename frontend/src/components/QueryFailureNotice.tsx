import { Alert, Button } from 'antd'

import { apiErrorMessage, apiErrorTraceId } from '../lib/api'

type QueryRead = {
  isError: boolean
  error: unknown
  refetch: () => Promise<unknown>
}

export default function QueryFailureNotice({ queries }: { queries: readonly QueryRead[] }) {
  const failed = queries.filter((query) => query.isError)
  if (!failed.length) return null
  const trace = apiErrorTraceId(failed[0].error)
  return (
    <Alert
      showIcon
      type="error"
      className="page-alert"
      title={apiErrorMessage(failed[0].error)}
      description={trace ? `Trace ID: ${trace}` : undefined}
      action={
        <Button
          aria-label="重试"
          onClick={() => void Promise.all(failed.map((query) => query.refetch()))}
        >
          重试
        </Button>
      }
    />
  )
}
