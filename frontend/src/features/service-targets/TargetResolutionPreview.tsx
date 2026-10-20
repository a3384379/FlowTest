import { Alert, Button, Card, Col, Input, InputNumber, Row, Select, Space, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import CatalogPagination from '../../components/CatalogPagination'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { useCatalogQuery } from '../../lib/catalog-query'
import { listApis } from '../api-console/api-service'
import {
  previewRequestTarget,
  type TargetPreviewChange,
  type TargetPreviewInput,
  type TargetPreviewResolution,
} from './service-target-service'

type Props = {
  projectId: string
  environmentId: string | null
  initialApi?: { id: string; name: string }
  change: TargetPreviewChange
  onReady: (ready: boolean) => void
}

export default function TargetResolutionPreview({
  projectId,
  environmentId,
  initialApi,
  change,
  onReady,
}: Props) {
  const [apiId, setApiId] = useState(initialApi?.id)
  const [search, setSearch] = useState('')
  const [version, setVersion] = useState<number | null>(null)
  const [override, setOverride] = useState('')
  const [variant, setVariant] = useState('default')
  const apis = useCatalogQuery(
    'target-preview-api-options',
    projectId,
    (page) => listApis(projectId, { page, pageSize: 20, search }),
    true,
    search,
  )
  const input = previewInput(change, environmentId, apiId, version, override, variant)
  const resolution = useQuery({
    queryKey: ['request-target-candidate-preview', projectId, input],
    queryFn: () => previewRequestTarget(projectId, input),
    retry: false,
    refetchOnWindowFocus: false,
  })
  const ready = resolution.isSuccess && !resolution.isFetching
  useEffect(() => onReady(ready), [onReady, ready])
  const options = apiOptions(apis.data?.items, initialApi)
  return (
    <Space orientation="vertical" className="full-width">
      <Alert
        type="info"
        showIcon
        title="只读目标解析"
        description="候选尚未保存。只计算所选接口在当前管理环境中的地址，不验证请求头、请求体、认证或业务结果。不会连接目标服务或读取凭据明文；缺少地址变量或认证查询参数时会明确显示无法计算。实际执行仍受出站策略约束。"
      />
      <label>
        预览接口
        <Select
          aria-label="预览接口"
          showSearch
          filterOption={false}
          style={{ width: '100%' }}
          value={apiId}
          placeholder="搜索并选择接口"
          onSearch={setSearch}
          onChange={setApiId}
          options={options}
          allowClear
        />
      </label>
      <CatalogPagination query={apis} label="预览接口" />
      <Row gutter={[12, 12]}>
        <Col xs={24} md={8}>
          <label>
            固定接口版本（留空为当前版本）
            <InputNumber
              aria-label="预览固定接口版本"
              min={1}
              value={version}
              onChange={setVersion}
              style={{ width: '100%' }}
            />
          </label>
        </Col>
        <Col xs={24} md={8}>
          <label>
            节点服务覆盖
            <Input
              aria-label="预览节点服务覆盖"
              value={override}
              onChange={(event) => setOverride(event.target.value)}
              placeholder="填写 service_key，可留空"
            />
          </label>
        </Col>
        <Col xs={24} md={8}>
          <label>
            节点地址变体
            <Input
              aria-label="预览节点地址变体"
              value={variant}
              onChange={(event) => setVariant(event.target.value)}
            />
          </label>
        </Col>
      </Row>
      {change.kind === 'api_binding' && (
        <Typography.Paragraph type="secondary">
          保存接口绑定会生成新的接口版本。固定历史版本保持原绑定；留空版本预览新的当前版本。
        </Typography.Paragraph>
      )}
      <QueryFailureNotice queries={[resolution]} />
      {resolution.isError && (
        <Button onClick={() => void resolution.refetch()}>重新解析候选</Button>
      )}
      {resolution.isFetching ? (
        <Typography.Text>正在解析当前候选</Typography.Text>
      ) : (
        resolution.data && (
          <Row gutter={[12, 12]}>
            <Col xs={24} md={12}>
              <ResolutionCard title="当前生效" resolution={resolution.data.before} />
            </Col>
            <Col xs={24} md={12}>
              <ResolutionCard title="待保存候选" resolution={resolution.data.after} />
            </Col>
          </Row>
        )
      )}
    </Space>
  )
}

function ResolutionCard({
  title,
  resolution,
}: {
  title: string
  resolution: TargetPreviewResolution
}) {
  return (
    <Card size="small" title={title}>
      {resolution.status === 'resolved' ? (
        <>
          <Typography.Paragraph copyable className="request-target-url">
            {resolution.url}
          </Typography.Paragraph>
          <Typography.Text type="secondary">
            服务 {resolution.service_key} · 变体 {resolution.endpoint_variant} · 地址修订{' '}
            {resolution.endpoint_revision} · 接口 v{resolution.api_version}
          </Typography.Text>
        </>
      ) : (
        <Alert
          type="warning"
          title="无法完整计算地址"
          description={
            <>
              <div>{resolution.error?.message}</div>
              <Typography.Text type="secondary">
                {resolution.error?.code} · 追踪 {resolution.error?.trace_id}
              </Typography.Text>
            </>
          }
        />
      )}
    </Card>
  )
}

function previewInput(
  change: TargetPreviewChange,
  environmentId: string | null,
  apiId: string | undefined,
  version: number | null,
  override: string,
  variant: string,
): TargetPreviewInput {
  return {
    change,
    environment_id: environmentId ?? undefined,
    api_id: apiId,
    api_version: version ?? undefined,
    service_override: override || undefined,
    endpoint_variant: variant || 'default',
  }
}
function apiOptions(
  apis: Array<{ id: string; name: string }> | undefined,
  initialApi: Props['initialApi'],
) {
  const options = apis?.map((item) => ({ value: item.id, label: item.name })) ?? []
  if (initialApi && !options.some((item) => item.value === initialApi.id))
    options.unshift({ value: initialApi.id, label: initialApi.name })
  return options
}
