import { Alert, Button, Spin } from 'antd'
import axios from 'axios'
import type { ReactNode } from 'react'

import { apiErrorWithTrace } from '../lib/api'

type OrganizationRead<T> = {
  data: T | undefined
  error: unknown
  isError: boolean
  isPending: boolean
  isFetching: boolean
  refetch: () => Promise<unknown>
}

export default function OrganizationQueryBoundary<T>({
  label,
  query,
  children,
}: {
  label: string
  query: OrganizationRead<T>
  children: (data: T) => ReactNode
}) {
  if (query.isError) {
    const forbidden = axios.isAxiosError(query.error) && query.error.response?.status === 403
    return (
      <Alert
        showIcon
        type={forbidden ? 'warning' : 'error'}
        title={forbidden ? `无权读取${label}` : `${label}加载失败`}
        description={apiErrorWithTrace(query.error)}
        action={
          <Button
            aria-label={`重试${label}`}
            loading={query.isFetching}
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            重试
          </Button>
        }
      />
    )
  }
  if (query.isPending || query.isFetching || query.data === undefined) {
    return (
      <Spin description={`正在加载${label}...`}>
        <div aria-label={`正在加载${label}`} style={{ minHeight: 96 }} />
      </Spin>
    )
  }
  return children(query.data)
}
