import { Tag } from 'antd'
import type { VerificationStatus } from './self-test-navigation'

const rawLabels = {
  not_run: '未运行',
  queued: '排队中',
  running: '运行中',
  passed: '通过',
  failed: '失败',
  cancelled: '已取消',
  quarantined: '已隔离',
} as const
export type SelfTestRawStatus = keyof typeof rawLabels
export function RawExecutionStatus({ status }: { status: SelfTestRawStatus | null }) {
  return (
    <Tag color={status === 'failed' ? 'error' : status === 'passed' ? 'success' : undefined}>
      原始执行：{status ? rawLabels[status] : '未运行'}
    </Tag>
  )
}
const verificationLabels: Record<VerificationStatus, string> = {
  pending: '未独立核验',
  matched: '符合预期',
  mismatched: '不符合预期',
  incomplete: '证据不完整',
  error: '核验读取失败',
  unsupported: '不支持',
}
export function VerificationStatusTag({ status }: { status: VerificationStatus }) {
  return (
    <Tag color={status === 'matched' ? 'success' : status === 'mismatched' ? 'error' : 'warning'}>
      独立核验：{verificationLabels[status]}
    </Tag>
  )
}
