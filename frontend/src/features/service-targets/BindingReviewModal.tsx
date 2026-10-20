import { Alert, Button, Modal, Space, Typography } from 'antd'
import { useState } from 'react'
import { isAxiosError } from 'axios'
import { apiErrorMessage, apiErrorTraceId } from '../../lib/api'
import type { ApiDefinition, Environment, RequestService } from '../../lib/api'
import TargetResolutionPreview from './TargetResolutionPreview'
import { type TargetPreviewChange } from './service-target-service'

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
  refreshing,
  onRefresh,
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
  refreshing: boolean
  onRefresh: () => void
  error: unknown
  onCancel: () => void
  onSave: () => void
}) {
  const [ready, setReady] = useState(false)
  const { originalId, change, label, initialApi } = candidateDetails(candidate)
  const stale = candidate.kind === 'environment' && candidate.environment.id !== environmentId
  function serviceName(id: string | null | undefined) {
    return id
      ? (services.find((item) => item.id === id)?.name ?? `服务 ${id}`)
      : '未绑定（继续继承下一层）'
  }
  return (
    <Modal
      open
      centered
      className="request-target-review-modal"
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
        disabled: readOnly || stale || !ready || refreshing || isVersionConflict(error),
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
        <APIRevisionNotice
          candidate={candidate}
          refreshing={refreshing}
          disabled={readOnly || submitting}
          onRefresh={onRefresh}
        />
        <TargetResolutionPreview
          projectId={projectId}
          environmentId={environmentId}
          initialApi={initialApi}
          change={change}
          onReady={setReady}
        />
        <BindingFailure error={error} />
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
      base_version: candidate.api.current_version,
    } satisfies TargetPreviewChange,
  }
}

function APIRevisionNotice({
  candidate,
  refreshing,
  disabled,
  onRefresh,
}: {
  candidate: BindingCandidate
  refreshing: boolean
  disabled: boolean
  onRefresh: () => void
}) {
  if (candidate.kind !== 'api') return null
  return (
    <Alert
      type="info"
      title={`已锁定接口当前版本 v${candidate.api.current_version}`}
      description="预览和保存使用同一基线版本。其他人发布或重新绑定后，保存会拒绝过期候选；读取最新版本会保留服务选择，并重新开始解析。"
      action={
        <Button disabled={disabled} loading={refreshing} onClick={onRefresh}>
          读取最新版本并重新分析
        </Button>
      }
    />
  )
}
function BindingFailure({ error }: { error: unknown }) {
  if (!error) return null
  const trace = apiErrorTraceId(error)
  return (
    <Alert
      type="error"
      title={apiErrorMessage(error)}
      description={
        <>
          <div>保存失败，候选仍保留。接口版本冲突时先读取最新版本重新分析。</div>
          {trace && <Typography.Text type="secondary">Trace ID: {trace}</Typography.Text>}
        </>
      }
    />
  )
}

function isVersionConflict(error: unknown): boolean {
  return (
    isAxiosError<{ error: { code: string } }>(error) &&
    error.response?.data?.error?.code === 'API_VERSION_CONFLICT'
  )
}
