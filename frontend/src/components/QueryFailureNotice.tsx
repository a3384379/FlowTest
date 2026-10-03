import { Alert, Button } from 'antd'

import { apiErrorMessage } from '../lib/api'

type QueryRead = {
  isError: boolean
  error: unknown
  refetch: () => Promise<unknown>
}

export default function QueryFailureNotice({ queries }: { queries: readonly QueryRead[] }) {
  const failed = queries.filter((query) => query.isError)
  if (!failed.length) return null
  return (
    <Alert
      showIcon
      type="error"
      className="page-alert"
      title={apiErrorMessage(failed[0].error)}
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
