import { Pagination, Space, Typography } from 'antd'
import QueryFailureNotice from './QueryFailureNotice'

type CatalogRead = {
  data?: { total: number; page_size: number }
  page: number
  setPage: (page: number) => void
  isError: boolean
  error: unknown
  refetch: () => Promise<unknown>
}

export default function CatalogPagination({
  query,
  label = '目录',
}: {
  query: CatalogRead
  label?: string
}) {
  return (
    <Space orientation="vertical" className="full-width">
      <QueryFailureNotice queries={[query]} />
      {query.data && (
        <Pagination
          size="small"
          current={query.page}
          pageSize={query.data.page_size}
          total={query.data.total}
          showSizeChanger={false}
          showTotal={(total) => `${label}共 ${total} 项`}
          onChange={query.setPage}
        />
      )}
      {!query.data && !query.isError && (
        <Typography.Text type="secondary">{label}尚未提供数据</Typography.Text>
      )}
    </Space>
  )
}
