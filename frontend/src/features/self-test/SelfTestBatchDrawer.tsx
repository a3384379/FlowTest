import { useState } from 'react'
import {
  Alert,
  Button,
  Checkbox,
  Descriptions,
  Drawer,
  InputNumber,
  Select,
  Space,
  Typography,
} from 'antd'
import { apiErrorWithTrace } from '../../lib/api'
import type { SelfTestState } from './use-self-tests'
import type { BatchInput, GenerationInput, ExecuteInput } from './self-test-contract'
import { useSelfTestCommand } from './use-self-test-command'
import {
  createGenerationBatch,
  createSelfTestRun,
  executeSelfTestAssets,
} from './self-test-service'
import SelfTestResourceSnapshot from './SelfTestResourceSnapshot'
import { generationModeLabels } from './self-test-labels'
import { isDispatchRecovery } from './self-test-dispatch-recovery'

export default function SelfTestBatchDrawer({
  state,
  operation,
  onClose,
}: {
  state: SelfTestState
  operation: 'generate' | 'native' | 'execute'
  onClose: () => void
}) {
  const controller = useBatchController({ state, operation, onClose })
  const { title, valid, command, submit } = controller
  return (
    <Drawer
      open
      title={title}
      size={640}
      className="self-test-drawer"
      onClose={onClose}
      destroyOnHidden
      footer={
        <Space wrap>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            disabled={!valid}
            loading={command.pending}
            onClick={() => void submit()}
          >
            {title}
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" style={{ width: '100%' }}>
        <BatchIdentity controller={controller} />
        <GenerationOptions controller={controller} />
        <BatchScopeOptions controller={controller} />
        {operation === 'execute' && (
          <SelfTestResourceSnapshot snapshot={state.selectedBatch?.resource_snapshot} />
        )}
        <BatchConfirmation controller={controller} />
      </Space>
    </Drawer>
  )
}

function BatchIdentity({ controller }: { controller: BatchController }) {
  const { state, installation } = controller
  return (
    <>
      <Descriptions
        column={1}
        size="small"
        items={[
          { key: 'binding', label: '绑定', children: state.binding?.name ?? '未提供' },
          {
            key: 'instance',
            label: '目标实例',
            children: state.binding?.target_instance_id ?? '未提供',
          },
          { key: 'installation', label: '安装记录', children: installation?.id ?? '未提供' },
          {
            key: 'fingerprint',
            label: '环境指纹',
            children: batchEnvironment(state),
          },
        ]}
      />
    </>
  )
}

function GenerationOptions({ controller }: { controller: BatchController }) {
  const { state, operation, mode, setMode, template, resetConfirm } = controller
  return (
    <>
      {operation === 'generate' && (
        <>
          <Select
            aria-label="MCP 生成模式"
            value={mode}
            options={
              template?.supported_modes.map((value) => ({
                value,
                label: generationModeLabels[value],
              })) ?? []
            }
            onChange={(value) => resetConfirm(() => setMode(value))}
            style={{ width: '100%' }}
          />
          <Alert
            type="info"
            showIcon
            title={
              state.binding?.host_status === 'available'
                ? '使用已登记外部宿主'
                : '未登记宿主：任务将等待外部宿主接入'
            }
            description="此操作只创建真实生成追踪任务，不自动审核、发布或正式执行。浏览器不会启动本机 MCP / Codex。"
          />
        </>
      )}
    </>
  )
}

function BatchScopeOptions({ controller }: { controller: BatchController }) {
  const {
    operation,
    scope,
    setScope,
    scenarioIds,
    setScenarioIds,
    seconds,
    setSeconds,
    requests,
    setRequests,
    calls,
    setCalls,
    template,
    resetConfirm,
  } = controller
  return (
    <>
      {operation !== 'execute' && (
        <>
          <Select
            aria-label="核验范围"
            value={scope}
            options={[
              { value: 'full_pack', label: '当前固定包全部场景' },
              { value: 'selected_suites', label: '选定套件（独立批次）' },
              { value: 'diagnostic_subset', label: '诊断子集（独立批次）' },
            ]}
            onChange={(value) => resetConfirm(() => setScope(value))}
            style={{ width: '100%' }}
          />
          {scope !== 'full_pack' && (
            <Select
              mode="multiple"
              aria-label="选择场景"
              value={scenarioIds}
              options={
                template?.scenarios.map((item) => ({
                  value: item.scenario_id,
                  label: `${item.scenario_id} · ${item.title}`,
                })) ?? []
              }
              onChange={(value) => resetConfirm(() => setScenarioIds(value))}
              style={{ width: '100%' }}
            />
          )}
          <Typography.Text>预算上限</Typography.Text>
          <Space wrap>
            <label>
              超时（秒）{' '}
              <InputNumber
                aria-label="超时秒数"
                min={30}
                max={600}
                value={seconds}
                onChange={(value) => resetConfirm(() => setSeconds(value ?? 600))}
              />
            </label>
            <label>
              请求数{' '}
              <InputNumber
                aria-label="最大请求数"
                min={1}
                max={500}
                value={requests}
                onChange={(value) => resetConfirm(() => setRequests(value ?? 500))}
              />
            </label>
            <label>
              工具调用{' '}
              <InputNumber
                aria-label="最大工具调用数"
                min={1}
                max={100}
                value={calls}
                onChange={(value) => resetConfirm(() => setCalls(value ?? 100))}
              />
            </label>
          </Space>
        </>
      )}
    </>
  )
}

function BatchConfirmation({ controller }: { controller: BatchController }) {
  const { state, operation, confirmed, setConfirmed, allowed, command } = controller
  return (
    <>
      <ExecuteNotice controller={controller} />
      {state.binding?.observer_status !== 'available' && (
        <Alert
          type="warning"
          showIcon
          title="Observer 未登记或已过期，执行结果不能据此认定独立验收通过。"
        />
      )}
      <Checkbox
        className="self-test-confirmation"
        checked={confirmed}
        onChange={(event) => setConfirmed(event.target.checked)}
      >
        我确认上述身份、范围和预算
        {operation === 'generate'
          ? '，仅创建生成任务'
          : operation === 'execute' && isDispatchRecovery(state.selectedBatch)
            ? '，恢复上述原生 Run 的派发'
            : '，启动正式执行'}
      </Checkbox>
      {!allowed && (
        <Alert type="warning" title="当前权限、绑定或资源状态不允许此操作，请重新读取。" />
      )}
      {Boolean(command.error) && (
        <Alert type="error" showIcon title={apiErrorWithTrace(command.error)} />
      )}
    </>
  )
}

function useBatchController({
  state,
  operation,
  onClose,
}: {
  state: SelfTestState
  operation: 'generate' | 'native' | 'execute'
  onClose: () => void
}) {
  const [confirmed, setConfirmed] = useState(false)
  const [mode, setMode] = useState<GenerationInput['generation_mode']>('deterministic_mcp')
  const [scope, setScope] = useState<BatchInput['verification_scope']>('full_pack')
  const [scenarioIds, setScenarioIds] = useState<string[]>([])
  const [seconds, setSeconds] = useState(600)
  const [requests, setRequests] = useState(500)
  const [calls, setCalls] = useState(100)
  const installation = state.selectedInstallation
  const template = state.templates.data?.items.find(
    (item) =>
      item.id === installation?.template_id && item.version === installation.template_version,
  )
  const allowed = { generate: state.canGenerate, native: state.canRun, execute: state.canExecute }[
    operation
  ]
  const command = useSelfTestCommand({
    identity: state.identity,
    selectionKey: `${operation}:${installation?.id}:${state.selectedBatch?.id}:${mode}:${scope}`,
    allowed: allowed && confirmed,
    send: (input: BatchInput | GenerationInput | ExecuteInput, key: string) => {
      if (operation === 'generate' && 'generation_mode' in input)
        return createGenerationBatch(state.projectId!, installation!.id, input, key)
      if (operation === 'execute' && 'resource_digest' in input)
        return executeSelfTestAssets(state.projectId!, state.selectedBatch!.id, input, key)
      if (operation === 'native' && 'scenario_ids' in input)
        return createSelfTestRun(state.projectId!, installation!.id, input, key)
      return Promise.reject(new Error('当前命令与确认范围不一致，请重新打开。'))
    },
  })
  function resetConfirm(change: () => void) {
    setConfirmed(false)
    change()
  }
  const valid = validBatchInput({
    allowed: allowed && supportedMode(operation, template, mode),
    confirmed,
    operation,
    digest: state.selectedBatch?.resource_digest,
    templateExists: Boolean(template),
    scope,
    count: scenarioIds.length,
    budget: { timeout_seconds: seconds, max_requests: requests, max_tool_calls: calls },
  })
  async function submit() {
    if (!valid) return
    const input =
      operation === 'execute'
        ? {
            resource_digest: state.selectedBatch!.resource_digest!,
            environment_fingerprint: state.selectedBatch!.environment_fingerprint,
            confirmed: true as const,
          }
        : {
            scenario_ids: scope === 'full_pack' ? [] : scenarioIds,
            verification_scope: scope,
            budget: { timeout_seconds: seconds, max_requests: requests, max_tool_calls: calls },
            ...(operation === 'generate' ? { generation_mode: mode, host_id: null } : {}),
          }
    const result = await command.execute(input)
    if (result) {
      state.select({
        binding: result.binding_id,
        installation: result.installation_id,
        batch: result.id,
        page: null,
        category: null,
        verification: null,
      })
      onClose()
    }
  }
  const title = {
    generate: '创建 MCP 生成任务',
    native: '运行固定基准',
    execute: isDispatchRecovery(state.selectedBatch) ? '恢复原运行派发' : '执行已发布固定版本',
  }[operation]

  return {
    state,
    operation,
    onClose,
    confirmed,
    setConfirmed,
    mode,
    setMode,
    scope,
    setScope,
    scenarioIds,
    setScenarioIds,
    seconds,
    setSeconds,
    requests,
    setRequests,
    calls,
    setCalls,
    installation,
    template,
    allowed,
    command,
    resetConfirm,
    valid,
    submit,
    title,
  }
}
type BatchController = ReturnType<typeof useBatchController>

function validBatchInput(input: {
  allowed: boolean
  confirmed: boolean
  operation: string
  digest: string | null | undefined
  templateExists: boolean
  scope: string
  count: number
  budget: import('./self-test-contract').SelfTestBudget
}) {
  if (!input.allowed || !input.confirmed) return false
  if (!validBudget(input.budget)) return false
  if (input.operation === 'execute') return Boolean(input.digest)
  return input.templateExists && (input.scope === 'full_pack' || input.count > 0)
}

function batchEnvironment(state: SelfTestState) {
  return (
    state.selectedBatch?.environment_fingerprint ??
    state.selectedInstallation?.environment_fingerprint ??
    '未提供'
  )
}

function ExecuteNotice({ controller }: { controller: BatchController }) {
  const { state, operation } = controller
  const recovering = isDispatchRecovery(state.selectedBatch)
  return (
    <>
      {operation === 'execute' && (
        <Alert
          type="info"
          showIcon
          title={recovering ? '继续派发既有原生运行' : '仅执行已发布且固定的真实版本'}
          description={`冻结场景：${state.selectedBatch?.expected_count ?? '未提供'}；资源摘要：${state.selectedBatch?.resource_digest ?? '未提供'}`}
        />
      )}
      {operation === 'execute' && recovering && (
        <Typography.Text>原生 Run：{state.selectedBatch!.plan_run_ids[0]}</Typography.Text>
      )}
    </>
  )
}

function supportedMode(
  operation: string,
  template: import('./self-test-contract').SelfTestTemplate | undefined,
  mode: GenerationInput['generation_mode'],
) {
  return operation !== 'generate' || Boolean(template?.supported_modes.includes(mode))
}

function validBudget(budget: import('./self-test-contract').SelfTestBudget) {
  return [
    { value: budget.timeout_seconds, min: 30, max: 600 },
    { value: budget.max_requests, min: 1, max: 500 },
    { value: budget.max_tool_calls, min: 1, max: 100 },
  ].every(
    (item) => Number.isInteger(item.value) && item.value >= item.min && item.value <= item.max,
  )
}
