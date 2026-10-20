import { protocolErrorPaths, type ProtocolErrorPath } from './protocol-error-details'
import { Alert, Button, Space, Typography } from 'antd'
import { apiErrorMessage, apiErrorTraceId } from '../../lib/api'

export default function ProtocolFailurePanel({
  error,
  onLocate,
  locating = false,
}: {
  error: unknown
  onLocate?: (path: ProtocolErrorPath) => void
  locating?: boolean
}) {
  if (!error) return null
  const trace = apiErrorTraceId(error)
  return (
    <div>
      <Alert
        type="error"
        showIcon
        title={apiErrorMessage(error)}
        description={trace ? `Trace ID: ${trace}` : undefined}
      />
      {onLocate &&
        protocolErrorPaths(error).map((path, index) => (
          <Space key={index} wrap>
            <Typography.Text code>{JSON.stringify(path)}</Typography.Text>
            <Button loading={locating} onClick={() => onLocate(path)}>
              定位错误对应契约
            </Button>
          </Space>
        ))}
    </div>
  )
}
