import { useEffect } from 'react'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Pagination,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { Link } from 'react-router-dom'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { apiErrorWithTrace } from '../../lib/api'
import { useSelfTests, type SelfTestState } from './use-self-tests'
import type { SelfTestBatch } from './self-test-contract'
import { selfTestReportPath } from './self-test-navigation'
import { RawExecutionStatus, VerificationStatusTag } from './SelfTestStatus'
import {
  phaseLabels,
  installationStatusLabels,
  runtimeProfileLabels,
  verdictLabels,
} from './self-test-labels'
import {
  SelfTestArtifacts,
  SelfTestReasons,
  SelfTestSourceEvidence,
  SelfTestVerificationEvidence,
} from './SelfTestEvidence'
import { batchHasCompleteVerdict, scenarioHasCompleteEvidence } from './self-test-verdict'
import SelfTestResourceSnapshot from './SelfTestResourceSnapshot'
import SelfTestGeneration from './SelfTestGeneration'
import SelfTestSetupDrawer from './SelfTestSetupDrawer'
import SelfTestBatchDrawer from './SelfTestBatchDrawer'
import { useSelfTestCommand } from './use-self-test-command'
import { cancelSelfTestBatch } from './self-test-service'
import { isDispatchRecovery } from './self-test-dispatch-recovery'
import { SelfTestCapabilities, SelfTestScopeBanner, SelfTestSidebar } from './SelfTestOverview'
import SelfTestIdentityValue from './SelfTestIdentityValue'
import './self-test.css'
type Dialog = 'setup' | 'generate' | 'native' | 'execute' | null

export default function SelfTestWorkspace() {
  const state = useSelfTests()
  const scope = `${state.identity.userId}:${state.identity.organizationId}:${state.identity.epoch}:${state.location.mode}:${state.location.bindingId}`
  const [dialog, setDialog] = useRouteScopedState<
    'setup' | 'generate' | 'native' | 'execute' | null
  >(state.projectId, scope, null)
  const cancel = useCancel(state)
  const batch = state.selectedBatch
  const select = state.select
  useEffect(() => {
    if (batch && !state.location.bindingId && !state.location.installationId)
      select({ binding: batch.binding_id, installation: batch.installation_id })
  }, [batch, state.location.bindingId, state.location.installationId, select])
  if (!state.projectId) return <Empty description="请先选择项目" />
  return (
    <section className="self-test-workspace" aria-label="系统自测工作台">
      <Card className="self-test-hero">
        <WorkspaceHeading state={state} setDialog={setDialog} cancel={cancel} />
        <Segmented
          aria-label="自测模式"
          value={state.location.mode}
          options={[
            { value: 'mcp_generation', label: 'MCP 生成闭环' },
            { value: 'native', label: '固定基准' },
          ]}
          onChange={(value) =>
            state.select({
              mode: String(value),
              installation: null,
              batch: null,
              scenario: null,
              page: null,
              category: null,
              verification: null,
              cursor: null,
            })
          }
        />
      </Card>
      <WorkspaceNotices state={state} cancel={cancel} />
      <WorkspaceSelectors state={state} />
      <SelfTestScopeBanner state={state} />
      <SelfTestCapabilities />
      <WorkspaceData state={state} />
      {dialog === 'setup' && <SelfTestSetupDrawer state={state} onClose={() => setDialog(null)} />}
      {dialog && dialog !== 'setup' && (
        <SelfTestBatchDrawer
          key={`${scope}:${state.location.installationId}:${state.location.batchId}:${dialog}`}
          state={state}
          operation={dialog}
          onClose={() => setDialog(null)}
        />
      )}
    </section>
  )
}
function BindingIdentity({ state }: { state: SelfTestState }) {
  const binding = state.binding!
  return (
    <Card size="small" title="已登记运行身份">
      <Space wrap>
        <Tag>{runtimeProfileLabels[binding.runtime_profile]}</Tag>
        <Tag color={binding.host_status === 'available' ? 'blue' : 'warning'}>
          {binding.host_status === 'available' ? '宿主已登记' : '等待外部宿主'}
        </Tag>
        <Tag color={binding.observer_status === 'available' ? 'blue' : 'warning'}>
          {binding.observer_status === 'available' ? 'Observer 已登记' : 'Observer 未核验'}
        </Tag>
      </Space>
      {binding.host_status !== 'available' && (
        <Alert
          type="warning"
          showIcon
          title="尚未登记有效宿主；生成任务将等待外部宿主，未运行不等于通过。"
        />
      )}
      {binding.observer_status !== 'available' && (
        <Alert type="warning" showIcon title="缺少有效 Observer，当前目标尚未完成独立核验。" />
      )}
      <SelfTestReasons reasons={binding.reason_codes} />
      <Descriptions
        className="self-test-binding-identity"
        size="small"
        layout="vertical"
        column={1}
        items={[
          { key: 'runner', label: 'Runner', value: binding.runner_instance_id },
          { key: 'target', label: 'Target', value: binding.target_instance_id },
          { key: 'address', label: '目标（只读）', value: binding.target_display },
          { key: 'fixture', label: 'Fixture（只读）', value: binding.fixture_display },
          { key: 'runner-build', label: 'Runner 构建', value: binding.builds.runner },
          { key: 'target-build', label: 'Target 构建', value: binding.builds.target },
          { key: 'fixture-build', label: 'Fixture 构建', value: binding.builds.fixture },
          { key: 'verifier-build', label: 'Verifier 构建', value: binding.builds.verifier },
        ].map(({ key, label, value }) => ({
          key,
          label,
          children: <SelfTestIdentityValue label={label} value={value} />,
        }))}
      />
    </Card>
  )
}
function BatchSummary({ state }: { state: SelfTestState }) {
  const batch = state.selectedBatch!
  const complete = [
    batchHasCompleteVerdict(batch),
    state.binding?.observer_status === 'available',
  ].every(Boolean)
  return (
    <Card title="冻结批次与验收状态">
      <Space wrap>
        <Tag>{batch.batch_kind === 'fixed_baseline' ? '固定基准' : 'MCP 生成'}</Tag>
        <Tag>{phaseLabels[batch.phase]}</Tag>
        <Tag color={batchVerdictColor(batch, complete)}>
          {complete
            ? '当前范围验收通过'
            : batch.verdict === 'failed'
              ? '验收失败'
              : '尚未完成独立验收'}
        </Tag>
        <Tag color={batch.provenance === 'local_untrusted' ? 'warning' : 'blue'}>
          {batch.provenance === 'local_untrusted' ? '本地未受信来源' : '受信 CI 来源'}
        </Tag>
      </Space>
      <Typography.Paragraph type="secondary">
        {batch.verification_scope === 'full_pack'
          ? '全部范围仅指当前冻结包，不代表整个系统的全部验收项。'
          : '本批次为选定范围，不代表全量验收。'}
      </Typography.Paragraph>
      <div className="self-test-summary">
        <div>
          <strong>{batch.expected_count}</strong>冻结预期场景
        </div>
        <div>
          <strong>{batch.required_scenario_set.length}</strong>必需场景
        </div>
        <div>
          <strong>{batch.plan_run_ids.length}</strong>正式原生运行
        </div>
      </div>
      <FrozenBatchDetails batch={batch} />
      <SelfTestReasons reasons={batch.reason_codes} />
    </Card>
  )
}
function batchVerdictColor(batch: SelfTestBatch, complete: boolean) {
  if (complete) return batch.verification_scope === 'full_pack' ? 'success' : 'blue'
  return batch.verdict === 'failed' ? 'error' : 'warning'
}
function FrozenBatchDetails({ batch }: { batch: SelfTestBatch }) {
  const historicalVerdict = batch.sealed_at ? batch.sealed_verdict : null
  return (
    <Descriptions
      size="small"
      column={1}
      items={[
        { key: 'id', label: '批次', children: batch.id },
        ...(historicalVerdict
          ? [
              {
                key: 'sealed-verdict',
                label: '封存验收结论（历史）',
                children: verdictLabels[historicalVerdict],
              },
            ]
          : []),
        { key: 'integrity', label: '证据完整性', children: batch.evidence_integrity },
        { key: 'cleanup', label: '清理', children: batch.cleanup_status },
        { key: 'manifest', label: '冻结清单摘要', children: batch.manifest_digest },
        { key: 'deadline', label: '截止时间', children: batch.deadline },
      ]}
    />
  )
}
function ScenarioResults({ state }: { state: SelfTestState }) {
  const projectId = state.projectId!
  const batch = state.selectedBatch!
  const rows = state.scenarios.isSuccess ? state.scenarios.data.items : []
  return (
    <Card title="场景结果（原始执行与独立核验）">
      <div className="self-test-controls">
        <Select
          aria-label="场景分类"
          value={state.location.category}
          options={[
            { value: '', label: '全部分类' },
            { value: 'api', label: 'API' },
            { value: 'engine', label: '执行引擎' },
            { value: 'mcp', label: 'MCP' },
          ]}
          onChange={(value) =>
            state.select({ category: value || null, page: null, scenario: null })
          }
        />
        <Select
          aria-label="核验结果筛选"
          value={state.location.verification}
          options={[
            { value: '', label: '全部核验状态' },
            { value: 'pending', label: '未独立核验' },
            { value: 'matched', label: '符合预期' },
            { value: 'mismatched', label: '不符合预期' },
            { value: 'incomplete', label: '证据不完整' },
            { value: 'error', label: '核验读取失败' },
            { value: 'unsupported', label: '不支持' },
          ]}
          onChange={(value) =>
            state.select({ verification: value || null, page: null, scenario: null })
          }
        />
        <Typography.Text type="secondary">
          当前页 {rows.length} 项；筛选总数 {state.scenarios.data?.total ?? '未提供'} 项
        </Typography.Text>
        {state.scenarios.data?.truncated && (
          <Tag color="warning">结果已截断，不能据此判定全量完成</Tag>
        )}
      </div>
      <Table
        rowKey="id"
        size="small"
        loading={state.scenarios.isLoading}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 1000 }}
        locale={{
          emptyText: state.scenarios.isError ? '场景证据读取失败' : '没有匹配的真实场景结果',
        }}
        columns={[
          {
            title: '场景',
            render: (_, row) => (
              <>
                <Typography.Text strong>{row.scenario_id}</Typography.Text>
                <div>{row.title}</div>
                <Typography.Text type="secondary">{row.variant_key}</Typography.Text>
              </>
            ),
          },
          {
            title: '冻结预期',
            render: (_, row) => (
              <span>
                {row.expected.status}
                {row.expected.error_code ? ` · ${row.expected.error_code}` : ''}
              </span>
            ),
          },
          {
            title: '原始执行',
            render: (_, row) => <RawExecutionStatus status={row.observed_status} />,
          },
          {
            title: '独立核验',
            render: (_, row) => (
              <VerificationStatusTag
                status={
                  scenarioHasCompleteEvidence(batch, row)
                    ? row.verification_status
                    : row.verification_status === 'matched'
                      ? 'incomplete'
                      : row.verification_status
                }
              />
            ),
          },
          {
            title: '正式报告',
            render: (_, row) => (
              <Space orientation="vertical">
                {row.executions
                  .filter((item) => item.execution_id)
                  .map((item, index) => (
                    <Link
                      key={item.run_item_id}
                      to={selfTestReportPath(
                        projectId,
                        { executionId: item.execution_id! },
                        { batchId: batch.id, scenarioId: row.scenario_id },
                      )}
                    >
                      执行 {index + 1} · {item.execution_id!.slice(0, 8)}
                    </Link>
                  ))}
                {!row.executions.some((item) => item.execution_id) && (
                  <Typography.Text type="secondary">尚无正式执行</Typography.Text>
                )}
              </Space>
            ),
          },
        ]}
        expandable={{
          expandedRowKeys: rows
            .filter((row) => row.scenario_id === state.location.scenarioId)
            .map((row) => row.id),
          onExpand: (expanded, row) =>
            state.select({ scenario: expanded ? row.scenario_id : null, page: null }),
          expandedRowRender: (row) => (
            <div className="self-test-evidence">
              <SelfTestVerificationEvidence projectId={projectId} batch={batch} scenario={row} />
              <SelfTestSourceEvidence
                projectId={projectId}
                batchId={batch.id}
                source={row.source}
              />
            </div>
          ),
        }}
      />
      <Pagination
        aria-label="场景分页"
        current={state.location.page}
        pageSize={20}
        total={state.scenarios.data?.total ?? 0}
        showSizeChanger={false}
        onChange={(page) => state.select({ page: String(page), scenario: null })}
      />
    </Card>
  )
}

function WorkspaceHeading({
  state,
  setDialog,
  cancel,
}: {
  state: SelfTestState
  setDialog: (value: Dialog) => void
  cancel: ReturnType<typeof useCancel>
}) {
  return (
    <>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>系统自测</Typography.Title>
          <Typography.Paragraph type="secondary">
            通过真实原生执行与独立证据，验证 FlowTest 的固定基准和 MCP 生成闭环。
          </Typography.Paragraph>
        </div>
        <Space wrap>
          <Button disabled={!state.canInitialize} onClick={() => setDialog('setup')}>
            初始化自测
          </Button>
          {state.location.mode === 'mcp_generation' ? (
            <Button
              type="primary"
              disabled={!state.canGenerate}
              onClick={() => setDialog('generate')}
            >
              创建 MCP 生成任务
            </Button>
          ) : (
            <Button type="primary" disabled={!state.canRun} onClick={() => setDialog('native')}>
              运行固定基准
            </Button>
          )}
          {(state.location.mode === 'mcp_generation' ||
            isDispatchRecovery(state.selectedBatch)) && (
            <Button
              disabled={!state.canExecute || !state.selectedBatch?.resource_digest}
              onClick={() => setDialog('execute')}
            >
              {isDispatchRecovery(state.selectedBatch) ? '恢复原运行派发' : '执行已发布产物'}
            </Button>
          )}
          <Button
            disabled={!state.canCancel}
            loading={cancel.pending}
            onClick={() => void cancel.execute(null)}
          >
            取消当前批次
          </Button>
          <Button
            onClick={() =>
              void Promise.all([
                state.bindings.refetch(),
                state.permissions.refetch(),
                ...(state.location.installationId ? [state.installation.refetch()] : []),
                ...(state.location.batchId
                  ? [state.batch.refetch(), state.scenarios.refetch()]
                  : []),
              ])
            }
          >
            刷新状态
          </Button>
        </Space>
      </div>
    </>
  )
}

function WorkspaceNotices({
  state,
  cancel,
}: {
  state: SelfTestState
  cancel: ReturnType<typeof useCancel>
}) {
  return (
    <>
      {state.location.error && <Alert type="error" showIcon title={state.location.error} />}
      <QueryFailureNotice
        queries={[
          state.templates,
          state.bindings,
          state.permissions,
          state.installation,
          state.runs,
          state.batch,
          state.generation,
          state.scenarios,
        ]}
      />
      {Boolean(cancel.error) && (
        <Alert type="error" showIcon title={apiErrorWithTrace(cancel.error)} />
      )}
      {state.scopeMismatch && (
        <Alert
          type="error"
          showIcon
          title="链接中的绑定、安装、批次或模式不一致。写入操作已关闭，请重新选择范围。"
        />
      )}
    </>
  )
}

function WorkspaceSelectors({ state }: { state: SelfTestState }) {
  return (
    <>
      <div className="self-test-controls">
        <Select
          aria-label="自测绑定"
          placeholder="选择已登记绑定"
          value={state.location.bindingId ?? undefined}
          loading={state.bindings.isLoading}
          options={
            state.bindings.isSuccess
              ? state.bindings.data.items.map((item) => ({ value: item.id, label: item.name }))
              : []
          }
          onChange={(value) =>
            state.select({
              binding: value,
              installation: null,
              batch: null,
              scenario: null,
              page: null,
              cursor: null,
            })
          }
        />
        <Select
          aria-label="安装记录"
          placeholder="选择安装记录"
          value={state.location.installationId ?? undefined}
          disabled={!state.binding}
          options={installationOptions(state)}
          onChange={(value) =>
            state.select({
              installation: value,
              batch: null,
              scenario: null,
              page: null,
              cursor: null,
            })
          }
        />
        <Select
          aria-label="自测批次"
          placeholder="选择真实批次"
          value={state.location.batchId ?? undefined}
          disabled={!state.selectedInstallation}
          options={
            state.runs.isSuccess
              ? state.runs.data.items
                  .filter(
                    (item) =>
                      (item.batch_kind === 'fixed_baseline') === (state.location.mode === 'native'),
                  )
                  .map((item) => ({
                    value: item.id,
                    label: `${item.batch_key} · ${phaseLabels[item.phase]}`,
                  }))
              : []
          }
          onChange={(value) => state.select({ batch: value, scenario: null, page: null })}
        />
        {state.runs.data?.has_more && (
          <Button onClick={() => state.select({ cursor: state.runs.data!.next_cursor })}>
            后续历史批次
          </Button>
        )}
        {state.runs.data?.truncated && <Tag color="warning">历史目录已截断</Tag>}
      </div>
    </>
  )
}

function WorkspaceData({ state }: { state: SelfTestState }) {
  const batch = state.selectedBatch
  return (
    <>
      <BindingSelectionNotice state={state} />
      <div className="self-test-workspace-layout">
        <div className="self-test-workspace-main">
          {state.selectedInstallation && (
            <Alert
              type={state.selectedInstallation.status === 'blocked' ? 'error' : 'info'}
              showIcon
              title={`安装状态：${installationStatusLabels[state.selectedInstallation.status]}`}
              description={<SelfTestReasons reasons={state.selectedInstallation.reason_codes} />}
            />
          )}
          {!batch && state.binding && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="尚未选择自测批次；这里不会展示模拟执行或默认通过数据。"
            />
          )}
          {batch && !state.scopeMismatch && (
            <>
              <BatchSummary state={state} />
              {state.location.mode === 'mcp_generation' && state.generation.isSuccess && (
                <SelfTestGeneration
                  projectId={state.projectId!}
                  generation={state.generation.data}
                  batch={batch}
                />
              )}
              <SelfTestResourceSnapshot snapshot={batch.resource_snapshot} />
              <ScenarioResults state={state} />
              <Card title="批次产物">
                <SelfTestArtifacts
                  projectId={state.projectId!}
                  batchId={batch.id}
                  artifacts={batch.artifacts}
                />
              </Card>
            </>
          )}
        </div>
        <div className="self-test-sidebar">
          <SelfTestSidebar state={state} />
          {state.binding && <BindingIdentity state={state} />}
        </div>
      </div>
    </>
  )
}

function useCancel(state: SelfTestState) {
  return useSelfTestCommand({
    identity: state.identity,
    selectionKey: state.location.batchId ?? '',
    allowed: state.canCancel,
    send: (_input: null, key: string) =>
      cancelSelfTestBatch(state.projectId!, state.selectedBatch!.id, key),
  })
}

function installationOptions(state: SelfTestState) {
  return (
    state.binding?.installations
      .filter((item) =>
        state.templates.data?.items.some(
          (template) =>
            template.pack_digest === item.pack_digest &&
            (template.batch_kind === 'fixed_baseline') === (state.location.mode === 'native'),
        ),
      )
      .map((item) => ({
        value: item.id,
        label: `${item.id.slice(0, 8)} · ${installationStatusLabels[item.status]}`,
      })) ?? []
  )
}

function BindingSelectionNotice({ state }: { state: SelfTestState }) {
  return (
    <>
      {!state.binding && !state.bindings.isLoading && (
        <Empty
          description={
            state.bindings.isError
              ? '绑定读取失败，请重试'
              : state.bindings.data?.items.length
                ? '请选择已登记且授权的绑定'
                : '没有已登记的自测绑定，请由部署管理员配置外部宿主与隔离目标'
          }
        />
      )}
    </>
  )
}
