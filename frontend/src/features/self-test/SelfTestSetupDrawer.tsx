import { useLayoutEffect, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Checkbox,
  Descriptions,
  Drawer,
  Empty,
  Select,
  Space,
  Table,
  Typography,
  Card,
  Steps,
  Tag,
} from 'antd'
import type {
  SelfTestBinding,
  SelfTestInstallation,
  SelfTestPreview,
  SelfTestTemplate,
} from './self-test-contract'
import type { SelfTestState } from './use-self-tests'
import { useSelfTestCommand } from './use-self-test-command'
import {
  getSelfTestInstallation,
  installSelfTest,
  previewSelfTestInstallation,
  createSelfTestRun,
} from './self-test-service'
import { selfTestIdentityIsCurrent, selfTestKeys } from './self-test-query-keys'
import { apiErrorWithTrace } from '../../lib/api'
import { SelfTestReasons } from './SelfTestEvidence'
import { previewCheckLabels, previewResourceLabels, previewActionLabels } from './self-test-labels'

export default function SelfTestSetupDrawer({
  state,
  onClose,
}: {
  state: SelfTestState
  onClose: () => void
}) {
  const templates =
    state.templates.data?.items.filter(
      (item) => (item.batch_kind === 'fixed_baseline') === (state.location.mode === 'native'),
    ) ?? []
  const [templateId, setTemplateId] = useState<string | undefined>(undefined)
  const template = templates.find((item) => item.id === templateId)
  return (
    <SetupForm
      key={`${state.identity.epoch}:${state.location.bindingId}:${state.location.mode}`}
      state={state}
      templates={templates}
      template={template}
      onTemplate={setTemplateId}
      onClose={onClose}
    />
  )
}
function SetupForm({
  state,
  templates,
  template,
  onTemplate,
  onClose,
}: {
  state: SelfTestState
  templates: SelfTestTemplate[]
  template: SelfTestTemplate | undefined
  onTemplate: (id: string) => void
  onClose: () => void
}) {
  const controller = useSetupController({ state, templates, template, onTemplate, onClose })
  const { changeTemplate } = controller
  return (
    <Drawer
      open
      title="初始化系统自测"
      size={720}
      className="self-test-drawer"
      onClose={onClose}
      destroyOnHidden
      footer={<SetupFooter controller={controller} />}
    >
      <Space orientation="vertical" style={{ width: '100%' }}>
        <Steps
          size="small"
          current={controller.previewMatches ? 2 : template && state.binding ? 1 : 0}
          items={[{ title: '选择模板' }, { title: '绑定环境' }, { title: '预览确认' }]}
        />
        <Alert
          type="info"
          showIcon
          title="仅使用已登记的隔离绑定"
          description="浏览器不会启动 Docker、Codex 或本地 MCP 宿主。地址只读；密钥不会在此展示。"
        />
        <Card size="small" title="已登记隔离环境">
          <BindingDetails binding={state.binding} />
        </Card>
        <Card size="small" title="自测模板" className="self-test-template-card">
          <Select
            aria-label="固定自测包"
            placeholder="选择服务端固定自测包"
            value={template?.id}
            options={templates.map((item) => ({
              value: item.id,
              label: `${item.title} · ${item.version}`,
            }))}
            onChange={changeTemplate}
            disabled={Boolean(controller.created)}
            style={{ width: '100%' }}
          />
          {template && (
            <Typography.Paragraph type="secondary">
              {template.version} · {template.scenarios.length} 个冻结场景 · {template.pack_digest}
            </Typography.Paragraph>
          )}
          {!templates.length && (
            <Empty description="暂无授权的固定自测包" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </Card>
        <SetupReceipt controller={controller} />
        <SetupPreview controller={controller} />
        {!state.canInitialize && (
          <Alert type="warning" title="当前权限或绑定状态不允许初始化，请刷新权限和绑定。" />
        )}
        <Typography.Text type="secondary">
          存在同名冲突或过期预检时，初始化操作均不可用。
        </Typography.Text>
      </Space>
    </Drawer>
  )
}
function BindingDetails({ binding }: { binding: SelfTestBinding | undefined }) {
  return binding ? (
    <Descriptions
      column={1}
      size="small"
      items={[
        { key: 'runner', label: 'Runner 实例', children: binding.runner_instance_id },
        { key: 'target', label: '目标实例', children: binding.target_instance_id },
        { key: 'address', label: '目标地址（只读）', children: binding.target_display },
        { key: 'fixture', label: 'Fixture（只读）', children: binding.fixture_display },
      ]}
    />
  ) : (
    <Alert type="warning" title="请先选择已登记且授权的绑定。" />
  )
}

function SetupFooter({ controller }: { controller: SetupController }) {
  const {
    state,
    template,
    onClose,
    previewing,
    runConfirmed,
    created,
    install,
    run,
    valid,
    preflight,
    apply,
  } = controller
  return (
    <>
      <div className="self-test-drawer-footer">
        <Button onClick={onClose}>关闭</Button>
        <Button
          disabled={!state.canInitialize || !template || Boolean(created)}
          loading={previewing}
          onClick={() => void preflight()}
        >
          运行安全预检
        </Button>
        <Button
          disabled={!valid || Boolean(created)}
          loading={install.pending}
          onClick={() => void apply(false)}
        >
          仅初始化
        </Button>
        {state.location.mode === 'native' && (
          <Button
            type="primary"
            disabled={!valid || !runConfirmed || Boolean(created)}
            loading={install.pending || run.pending}
            onClick={() => void apply(true)}
          >
            初始化并运行
          </Button>
        )}
      </div>
    </>
  )
}

function SetupReceipt({ controller }: { controller: SetupController }) {
  const { runConfirmed, created, installed, waitingRun, run, startRun } = controller
  return (
    <>
      <SetupFailure controller={controller} />
      {created && (
        <Alert
          type="info"
          showIcon
          title={
            installed?.status === 'ready' ? '初始化已完成' : '初始化任务已创建，等待外部宿主完成'
          }
          description={
            run.error
              ? '初始化成功，启动失败。重试只启动运行，不重复初始化。'
              : waitingRun
                ? '已记录运行确认，资源就绪后在当前页面启动。离开或权限失效会停止后续操作。'
                : undefined
          }
        />
      )}
      {created && Boolean(run.error) && (
        <Button disabled={run.pending || !runConfirmed} onClick={() => void startRun()}>
          重试启动运行
        </Button>
      )}
    </>
  )
}

function SetupPreview({ controller }: { controller: SetupController }) {
  const {
    state,
    preview,
    confirmed,
    setConfirmed,
    runConfirmed,
    setRunConfirmed,
    created,
    now,
    previewMatches,
  } = controller
  return (
    <>
      {previewMatches && preview && (
        <>
          <Descriptions
            column={1}
            size="small"
            items={[
              { key: 'fingerprint', label: '预检指纹', children: preview.fingerprint },
              { key: 'expires', label: '预检有效期', children: preview.expires_at },
              {
                key: 'scope',
                label: '范围与运行预算上限',
                children: `${preview.template.scenarios.length} 个场景；600 秒 / 500 请求 / 100 工具调用`,
              },
            ]}
          />
          <Card size="small" title="安全检查">
            <Table
              rowKey="code"
              size="small"
              pagination={false}
              dataSource={preview.checks}
              columns={[
                { title: '预检项', dataIndex: 'code' },
                {
                  title: '结果',
                  dataIndex: 'status',
                  render: (value: keyof typeof previewCheckLabels) => (
                    <Tag
                      color={
                        value === 'passed' ? 'blue' : value === 'blocked' ? 'error' : 'warning'
                      }
                    >
                      {previewCheckLabels[value]}
                    </Tag>
                  ),
                },
                { title: '说明', dataIndex: 'message' },
              ]}
            />
          </Card>
          <Card size="small" title="资源预览">
            <Table
              rowKey="kind"
              size="small"
              pagination={false}
              dataSource={preview.resources}
              columns={[
                {
                  title: '资源',
                  dataIndex: 'kind',
                  render: (value: keyof typeof previewResourceLabels) =>
                    previewResourceLabels[value],
                },
                {
                  title: '处理',
                  dataIndex: 'action',
                  render: (value: keyof typeof previewActionLabels) => (
                    <Tag color={value === 'conflict' ? 'warning' : 'blue'}>
                      {previewActionLabels[value]}
                    </Tag>
                  ),
                },
                { title: '数量', dataIndex: 'count' },
              ]}
            />
            <SelfTestReasons reasons={preview.conflicts} />
          </Card>
          {Date.parse(preview.expires_at) <= now && (
            <Alert type="warning" title="预检已过期，请重新预检并确认。" />
          )}
          <Checkbox
            className="self-test-confirmation"
            checked={confirmed}
            disabled={!preview.can_apply || Boolean(preview.conflicts.length) || Boolean(created)}
            onChange={(event) => setConfirmed(event.target.checked)}
          >
            我确认按预检范围创建或复用隔离资源
          </Checkbox>
          {state.location.mode === 'native' && (
            <Checkbox
              className="self-test-confirmation"
              checked={runConfirmed}
              disabled={
                !state.executeAllowed || !state.binding?.actions.can_execute || Boolean(created)
              }
              onChange={(event) => setRunConfirmed(event.target.checked)}
            >
              我另外确认运行当前固定包，并接受上述预算
            </Checkbox>
          )}
        </>
      )}
    </>
  )
}

function useSetupController({
  state,
  templates,
  template,
  onTemplate,
  onClose,
}: {
  state: SelfTestState
  templates: SelfTestTemplate[]
  template: SelfTestTemplate | undefined
  onTemplate: (id: string) => void
  onClose: () => void
}) {
  const [preview, setPreview] = useState<SelfTestPreview | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [failure, setFailure] = useState<unknown>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [runConfirmed, setRunConfirmed] = useState(false)
  const [created, setCreated] = useState<SelfTestInstallation | null>(null)
  const [now, setNow] = useState(Date.now)
  const active = useRef(true)
  const revision = useRef(0)
  const runIntent = useRef(false)
  const [waitingRun, setWaitingRun] = useState(false)
  const started = useRef(false)
  useEffect(() => {
    active.current = true
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => {
      active.current = false
      window.clearInterval(timer)
    }
  }, [])
  useEffect(() => {
    if (!preview || created) return
    const timer = window.setTimeout(
      () => {
        setConfirmed(false)
        setRunConfirmed(false)
      },
      Math.min(2147483647, Math.max(0, Date.parse(preview.expires_at) - Date.now())),
    )
    return () => window.clearTimeout(timer)
  }, [preview, created])
  const context = `${state.location.bindingId}:${template?.id}:${template?.version}`
  const currentContext = useRef(context)
  useLayoutEffect(() => {
    currentContext.current = context
  }, [context])
  const projectId = state.projectId!
  const install = useSelfTestCommand({
    identity: state.identity,
    selectionKey: `${context}:${state.location.installationId}:${state.location.batchId}`,
    allowed: state.canInitialize,
    send: (input: Parameters<typeof installSelfTest>[1], key: string) =>
      installSelfTest(projectId, input, key),
  })
  const ready = useQuery({
    queryKey: selfTestKeys.installation(state.identity, created?.id ?? null),
    queryFn: ({ signal }) => getSelfTestInstallation(projectId, created!.id, signal),
    enabled: Boolean(created),
    refetchInterval: (query) =>
      query.state.data && !['ready', 'blocked', 'archived'].includes(query.state.data.status)
        ? 2000
        : false,
    refetchIntervalInBackground: false,
  })
  const installed = ready.isSuccess ? ready.data : created
  const run = useSelfTestCommand({
    identity: state.identity,
    selectionKey: `${context}:${created?.id}:${state.location.installationId}:${state.location.batchId}`,
    allowed: Boolean(
      [
        state.canInitialize,
        state.executeAllowed,
        runConfirmed,
        installed?.status === 'ready',
        state.location.installationId === installed?.id,
        installed?.actions.can_execute,
      ].every(Boolean),
    ),
    send: (input: Parameters<typeof createSelfTestRun>[2], key: string) =>
      createSelfTestRun(projectId, installed!.id, input, key),
  })
  async function startRun() {
    if (!installed || started.current) return
    started.current = true
    runIntent.current = false
    setWaitingRun(false)
    const result = await run.execute({
      scenario_ids: [],
      verification_scope: 'full_pack',
      budget: { timeout_seconds: 600, max_requests: 500, max_tool_calls: 100 },
    })
    if (result) {
      state.select({
        binding: result.binding_id,
        installation: result.installation_id,
        batch: result.id,
        page: null,
      })
      onClose()
    } else started.current = false
  }
  useEffect(() => {
    if (
      runIntent.current &&
      installed?.status === 'ready' &&
      runConfirmed &&
      !started.current &&
      state.canInitialize &&
      state.location.installationId === installed.id &&
      state.executeAllowed &&
      installed.actions.can_execute
    )
      void startRun()
  })
  function receiptIsCurrent(token: number, captured: string) {
    return [
      active.current,
      token === revision.current,
      currentContext.current === captured,
      selfTestIdentityIsCurrent(state.identity),
    ].every(Boolean)
  }
  async function preflight() {
    if ([!state.canInitialize, !template, !state.binding, previewing].some(Boolean)) return
    const token = ++revision.current
    const captured = context
    setPreviewing(true)
    setPreview(null)
    setConfirmed(false)
    setRunConfirmed(false)
    setFailure(null)
    try {
      const result = await previewSelfTestInstallation(projectId, {
        binding_id: state.binding!.id,
        template_id: template!.id,
        template_version: template!.version,
      })
      if (receiptIsCurrent(token, captured)) setPreview(result)
    } catch (error) {
      if (receiptIsCurrent(token, captured)) setFailure(error)
    } finally {
      if (active.current && token === revision.current) setPreviewing(false)
    }
  }
  const previewMatches = matchingPreview(preview, template, state.binding)
  const valid = validPreview(previewMatches, preview, now, confirmed, state.canInitialize)
  async function apply(andRun: boolean) {
    if (!valid || !preview || !template || !state.binding || created || (andRun && !runConfirmed))
      return
    runIntent.current = andRun
    setWaitingRun(andRun)
    const result = await install.execute({
      template_id: template.id,
      template_version: template.version,
      binding_id: state.binding.id,
      preview_fingerprint: preview.fingerprint,
      preview_expires_at: preview.expires_at,
    })
    if (result) {
      setCreated(result)
      state.select({ installation: result.id, batch: null })
      if (!andRun) onClose()
    }
  }
  function changeTemplate(id: string) {
    revision.current++
    setPreview(null)
    setConfirmed(false)
    setRunConfirmed(false)
    setPreviewing(false)
    onTemplate(id)
  }

  return {
    state,
    templates,
    template,
    onTemplate,
    onClose,
    preview,
    previewing,
    failure,
    confirmed,
    setConfirmed,
    runConfirmed,
    setRunConfirmed,
    created,
    installed,
    now,
    waitingRun,
    install,
    run,
    valid,
    previewMatches,
    preflight,
    apply,
    changeTemplate,
    startRun,
  }
}
type SetupController = ReturnType<typeof useSetupController>

function matchingPreview(
  preview: SelfTestPreview | null,
  template: SelfTestTemplate | undefined,
  binding: SelfTestBinding | undefined,
) {
  if (!preview || !template || !binding) return false
  return [
    preview.template.id === template.id,
    preview.template.version === template.version,
    preview.binding_id === binding.id,
  ].every(Boolean)
}
function validPreview(
  matches: boolean,
  preview: SelfTestPreview | null,
  now: number,
  confirmed: boolean,
  allowed: boolean,
) {
  if (!preview) return false
  return [
    matches,
    preview.can_apply,
    !preview.conflicts.length,
    Date.parse(preview.expires_at) > now,
    confirmed,
    allowed,
  ].every(Boolean)
}

function SetupFailure({ controller }: { controller: SetupController }) {
  const { failure, install, run } = controller
  return (
    <>
      {Boolean(failure || install.error || run.error) && (
        <Alert
          type="error"
          showIcon
          title={apiErrorWithTrace(failure || install.error || run.error)}
        />
      )}
    </>
  )
}
