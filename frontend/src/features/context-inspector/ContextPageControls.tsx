import { Alert, Pagination } from 'antd'
import { apiErrorMessage } from '../../lib/api'

type Props = { page: number; total: number; onChange: (page: number) => void; error?: Error | null }

export default function ContextPageControls({ page, total, onChange, error }: Props) {
  return (
    <>
      {error && <Alert type="error" title={apiErrorMessage(error)} />}
      <Pagination
        aria-label="上下文分页"
        size="small"
        current={page}
        pageSize={20}
        total={total}
        showSizeChanger={false}
        hideOnSinglePage
        onChange={onChange}
      />
    </>
  )
}
