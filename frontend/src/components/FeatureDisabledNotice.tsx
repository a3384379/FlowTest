import type { V3FeatureFlags } from '../features/capabilities/capability-service'
import { Alert } from 'antd'

export default function FeatureDisabledNotice({
  flags,
  feature,
  label,
}: {
  flags?: V3FeatureFlags
  feature: keyof V3FeatureFlags
  label: string
}) {
  if (flags?.[feature] !== false) return null
  return (
    <Alert
      showIcon
      type="info"
      className="page-alert"
      title={`${label}当前关闭`}
      description="管理员启用此能力后可管理资源并执行任务。"
    />
  )
}
