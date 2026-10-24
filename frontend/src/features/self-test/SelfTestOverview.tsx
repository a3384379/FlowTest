import {
  ApiOutlined,
  AuditOutlined,
  ExperimentOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { Alert, Button, Card, Descriptions, Empty, Space, Tag, Typography } from 'antd'
import type { SelfTestState } from './use-self-tests'
import { phaseLabels } from './self-test-labels'
import { batchHasCompleteVerdict } from './self-test-verdict'
import type { SelfTestBatch, SelfTestBinding } from './self-test-contract'

const capabilities = [
  {
    title: '接口回归',
    description: '使用真实接口与冻结输入，验证数据传递和关键业务行为。',
    icon: <ApiOutlined />,
  },
  {
    title: '引擎验证',
    description: '检查断言、超时与控制流的实际执行，保留原始失败状态。',
    icon: <ExperimentOutlined />,
  },
  {
    title: '独立核验',
    description: '对照冻结预期与独立请求证据，核实结果、来源和完整性。',
    icon: <AuditOutlined />,
  },
]
export function SelfTestCapabilities() {
  return (
    <div className="self-test-capabilities" aria-label="自测能力">
      {capabilities.map((item) => (
        <Card size="small" key={item.title}>
          <span className="self-test-capability-icon">{item.icon}</span>
          <div>
            <Typography.Text strong>{item.title}</Typography.Text>
            <Typography.Paragraph type="secondary">{item.description}</Typography.Paragraph>
          </div>
        </Card>
      ))}
    </div>
  )
}

export function SelfTestScopeBanner({ state }: { state: SelfTestState }) {
  const batch = state.selectedBatch
  if (!batch) return null
  const templateCount = scopeTemplateCount(state)
  const complete = [
    batchHasCompleteVerdict(batch),
    state.binding?.observer_status === 'available',
  ].every(Boolean)
  const full = batch.verification_scope === 'full_pack'
  return (
    <Alert
      className="self-test-scope-banner"
      showIcon
      type={scopeBannerType(batch, complete)}
      title={
        complete
          ? full
            ? '当前冻结包核验已完成'
            : '选定子集核验已完成，不代表全量通过'
          : '核验未完成'
      }
      description={
        <Space wrap>
          <span>
            范围：{full ? '当前冻结包' : '所选子集'} · {batch.expected_count}
            {templateCount === undefined ? '' : ` / ${templateCount}`} 场景
          </span>
          <span>
            {complete
              ? '原始执行结果与独立核验结论分别保留。'
              : '部分场景仍在等待执行、清理或独立证据。'}
          </span>
        </Space>
      }
    />
  )
}

export function SelfTestSidebar({ state }: { state: SelfTestState }) {
  return (
    <aside className="self-test-sidebar" aria-label="隔离检查与最近批次">
      <IsolationChecks binding={state.binding} />
      <RecentBatches state={state} />
    </aside>
  )
}
function scopeTemplateCount(state: SelfTestState) {
  return state.templates.data?.items.find(
    (item) => item.id === state.selectedInstallation?.template_id,
  )?.scenarios.length
}
function scopeBannerType(batch: SelfTestBatch, complete: boolean) {
  if (complete && batch.verification_scope === 'full_pack') return 'success'
  return batch.verdict === 'failed' ? 'error' : 'warning'
}
function Availability({ available, label }: { available: boolean; label: string }) {
  return <Tag color={available ? 'blue' : 'warning'}>{available ? label : '未核验'}</Tag>
}
function IsolationChecks({ binding }: { binding: SelfTestBinding | undefined }) {
  return (
    <Card
      size="small"
      title={
        <Space>
          <SafetyCertificateOutlined />
          隔离检查
        </Space>
      }
    >
      <Descriptions
        size="small"
        column={1}
        items={[
          { key: 'target', label: '目标实例', children: binding?.target_instance_id ?? '未登记' },
          {
            key: 'host',
            label: '外部宿主',
            children: (
              <Availability available={binding?.host_status === 'available'} label="已登记" />
            ),
          },
          {
            key: 'observer',
            label: '独立证据域',
            children: (
              <Availability
                available={binding?.observer_status === 'available'}
                label="Observer 已登记"
              />
            ),
          },
          { key: 'scope', label: '目标地址', children: binding?.target_display ?? '尚无授权绑定' },
        ]}
      />
      <Typography.Text type="secondary">
        登记状态仅表示当前绑定可识别；独立验收以封存证据为准。
      </Typography.Text>
    </Card>
  )
}
function RecentBatches({ state }: { state: SelfTestState }) {
  const batches = state.runs.isSuccess
    ? state.runs.data.items
        .filter(
          (item) => (item.batch_kind === 'fixed_baseline') === (state.location.mode === 'native'),
        )
        .slice(0, 4)
    : []
  return (
    <Card size="small" title="最近批次">
      {batches.length ? (
        <div className="self-test-recent-batches">
          {batches.map((batch) => (
            <Button
              key={batch.id}
              type="text"
              onClick={() => state.select({ batch: batch.id, scenario: null, page: null })}
            >
              <span>
                <strong>{batch.batch_key}</strong>
                <small>{batch.created_at}</small>
              </span>
              <Tag>{phaseLabels[batch.phase]}</Tag>
            </Button>
          ))}
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无真实批次" />
      )}
      {state.runs.data?.has_more && (
        <Typography.Text type="secondary">
          此处仅显示当前已读取的最近记录，可通过批次选择器继续翻页。
        </Typography.Text>
      )}
    </Card>
  )
}
