import { Alert, Button, Space } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { contractServicePath } from './contract-service-location'
import type { useContractServiceContext } from './use-contract-service-context'

export default function ContractServiceContextNotice({
  projectId,
  context,
  description,
}: {
  projectId: string | null
  context: ReturnType<typeof useContractServiceContext>
  description: string
}) {
  const [params, setParams] = useSearchParams()
  if (!context.enabled || (!context.selection.id && !context.selection.error)) return null
  function clear() {
    const next = new URLSearchParams(params)
    next.delete('contractServiceId')
    next.delete('service_id')
    if (next.get('focus')?.startsWith('contract_service:')) next.delete('focus')
    setParams(next)
  }
  return (
    <Space orientation="vertical" style={{ width: '100%', marginBottom: 16 }}>
      {context.selection.error && <Alert type="error" showIcon title={context.selection.error} />}
      <QueryFailureNotice queries={[context.selected]} />
      {context.selected.data && (
        <Alert
          type="info"
          showIcon
          title={`服务上下文：${context.selected.data.display_name}`}
          description={`${context.selected.data.service_key} · ${context.selected.data.id}。${description}`}
        />
      )}
      <Space>
        <Button onClick={clear}>查看项目全部范围</Button>
        {projectId && context.selection.id && (
          <Link to={contractServicePath(projectId, 'services', context.selection.id)}>
            返回该服务详情
          </Link>
        )}
      </Space>
    </Space>
  )
}
