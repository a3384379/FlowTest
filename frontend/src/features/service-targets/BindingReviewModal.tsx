import { useQueries } from '@tanstack/react-query'
import { Alert, Modal, Space, Typography } from 'antd'
import { useState } from 'react'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { apiErrorMessage } from '../../lib/api'
import type { ApiDefinition, Environment, RequestService } from '../../lib/api'
import TargetResolutionPreview from './TargetResolutionPreview'
import TargetImpactPanel from './TargetImpactPanel'
import { getServiceTargetImpactPreview, type TargetPreviewChange } from './service-target-service'

export type BindingCandidate = (
  | { kind: 'environment'; environment: Environment; serviceId: string | null }
  | { kind: 'api'; api: ApiDefinition; serviceId: string | null }
) & { session: number }

export default function BindingReviewModal({
  projectId,
  environmentId,
  candidate,
  services,
  readOnly,
  submitting,
  error,
  onCancel,
  onSave,
}: {
  projectId: string
  environmentId: string | null
  candidate: BindingCandidate
  services: RequestService[]
  readOnly: boolean
  submitting: boolean
  error: unknown
  onCancel: () => void
  onSave: () => void
}) {
  const [ready, setReady] = useState(false)
  const { originalId, change, label, initialApi } = candidateDetails(candidate)
  const serviceIds = [
    ...new Set([originalId, candidate.serviceId].filter((id): id is string => Boolean(id))),
  ]
  const impacts = useQueries({
    queries: serviceIds.map((id) => ({
      queryKey: ['request-target-service-impact', projectId, id],
      queryFn: () => getServiceTargetImpactPreview(projectId, id),
      retry: false,
    })),
  })
  const stale = candidate.kind === 'environment' && candidate.environment.id !== environmentId
  function serviceName(id: string | null | undefined) {
    return id
      ? (services.find((item) => item.id === id)?.name ?? `服务 ${id}`)
      : '未绑定（继续继承下一层）'
  }
  return (
    <Modal
      open
      title="确认默认服务变更"
      width={920}
      okText="确认保存"
      cancelText="取消候选"
      mask={{ closable: false }}
      closable={!submitting}
      cancelButtonProps={{ disabled: submitting }}
      confirmLoading={submitting}
      onCancel={onCancel}
      onOk={onSave}
      okButtonProps={{
        disabled:
          readOnly || stale || !ready || impacts.some((item) => !item.isSuccess || item.isFetching),
      }}
    >
      <Space orientation="vertical" className="full-width">
        <Alert
          type="warning"
          showIcon
          title={`${label} · 尚未保存`}
          description="更改下拉只生成本地候选。确认保存后才会更新配置；取消保留服务器当前值。"
        />
        {stale && (
          <Alert type="error" title="管理环境已切换，该候选已失效。请取消后在对应环境重新编辑。" />
        )}
        <Typography.Paragraph>
          当前生效：{serviceName(originalId)} → 待保存候选：{serviceName(candidate.serviceId)}
        </Typography.Paragraph>
        <QueryFailureNotice queries={impacts} />
        {impacts.map((impact, index) => (
          <section key={serviceIds[index]}>
            <Typography.Title level={5}>
              服务引用范围：{serviceName(serviceIds[index])}
            </Typography.Title>
            <TargetImpactPanel impact={impact.data} />
          </section>
        ))}
        <TargetResolutionPreview
          projectId={projectId}
          environmentId={environmentId}
          initialApi={initialApi}
          change={change}
          onReady={setReady}
        />
        {Boolean(error) && (
          <Alert
            type="error"
            title={apiErrorMessage(error)}
            description="保存失败，候选仍保留，可重试确认保存。"
          />
        )}
      </Space>
    </Modal>
  )
}

function candidateDetails(candidate: BindingCandidate) {
  if (candidate.kind === 'environment')
    return {
      originalId: candidate.environment.default_service_id,
      label: candidate.environment.name,
      initialApi: undefined,
      change: {
        kind: 'environment_default',
        environment_id: candidate.environment.id,
        service_id: candidate.serviceId,
      } satisfies TargetPreviewChange,
    }
  return {
    originalId: candidate.api.service_id,
    label: candidate.api.name,
    initialApi: candidate.api,
    change: {
      kind: 'api_binding',
      api_id: candidate.api.id,
      service_id: candidate.serviceId,
    } satisfies TargetPreviewChange,
  }
}
