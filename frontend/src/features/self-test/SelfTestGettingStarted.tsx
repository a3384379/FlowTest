import { useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Space, Steps, Tabs, Typography } from 'antd'
import type { SelfTestState } from './use-self-tests'

export type SelfTestHelpTab = 'usage' | 'deployment'

export function SelfTestGettingStarted({ onConfigure }: { onConfigure: () => void }) {
  return (
    <Card className="self-test-getting-started">
      <Typography.Title level={3}>先接入自测环境</Typography.Title>
      <Typography.Paragraph type="secondary">
        当前项目还没有可用的自测绑定。先接入隔离目标和代理，再初始化模板、创建真实批次。
      </Typography.Paragraph>
      <Steps
        size="small"
        current={0}
        items={[
          { title: '接入环境', content: '部署管理员登记隔离目标与代理' },
          { title: '初始化模板', content: '选择绑定，预检并安装测试资产' },
          { title: '运行与核验', content: '运行用例，查看独立核验报告' },
        ]}
      />
      <Button type="primary" onClick={onConfigure}>
        查看环境接入步骤
      </Button>
    </Card>
  )
}

export default function SelfTestHelpDrawer({
  state,
  initialTab,
  onClose,
}: {
  state: SelfTestState
  initialTab: SelfTestHelpTab
  onClose: () => void
}) {
  const [tab, setTab] = useState<string>(initialTab)
  return (
    <Drawer
      open
      title="自测配置与使用指南"
      size={760}
      className="self-test-drawer"
      onClose={onClose}
      destroyOnHidden
      footer={
        <div className="self-test-drawer-footer">
          <Button
            loading={state.bindings.isFetching || state.permissions.isFetching}
            onClick={() =>
              void Promise.all([state.bindings.refetch(), state.permissions.refetch()])
            }
          >
            重新检查接入
          </Button>
          <Button onClick={onClose}>返回自测工作台</Button>
        </div>
      }
    >
      <Tabs
        activeKey={tab}
        onChange={setTab}
        destroyOnHidden
        items={[
          { key: 'usage', label: '如何自测', children: <UsageGuide /> },
          { key: 'deployment', label: '部署登记', children: <DeploymentGuide state={state} /> },
        ]}
      />
    </Drawer>
  )
}

function UsageGuide() {
  return (
    <div className="self-test-help-content">
      <Alert
        type="info"
        showIcon
        title="第一次使用，先完成环境接入"
        description="在“部署登记”中查看配置位置与当前项目接入清单。绑定可用后，页面中的初始化和运行操作才会开放。"
      />
      <Steps
        orientation="vertical"
        items={[
          {
            title: '选择自测绑定',
            content:
              '从“自测绑定”选择管理员登记的环境，核对隔离检查中的目标、执行代理与独立核验代理。',
          },
          {
            title: '初始化自测',
            content:
              '点击“初始化自测”，选择模板，检查预检结果，再确认安装；等待安装记录显示“已就绪”。',
          },
          {
            title: '选择运行方式',
            content:
              '固定基准：点击“运行固定基准”，确认范围后运行。MCP 生成闭环：创建生成任务，审核并发布 Workflow 与 Case，再点击“执行已发布产物”。',
          },
          {
            title: '查看批次与报告',
            content:
              '选择本次真实批次，查看场景结果；从执行链接进入报告的“独立核验”和“生成来源”面板。原始执行状态与核验结论分别显示。',
          },
        ]}
      />
      <Alert
        type="warning"
        showIcon
        title="真实模型需要单独接入与授权"
        description="确定性 MCP 模式可以用于无模型自测。真实宿主/LLM 模式还需要宿主、模型与预算授权；未接入时保持未运行。查看者可阅读指南，安装与执行仍需要项目权限。"
      />
    </div>
  )
}

function bindingStatus(state: SelfTestState): string {
  if (state.bindings.isError) return '读取失败，请重新检查'
  if (!state.bindings.isSuccess) return '正在读取登记状态'
  if (state.binding) return state.binding.name
  const count = state.bindings.data.items.length
  return count ? `已登记 ${count} 个可见绑定，请在页面选择` : '当前项目尚无可见绑定'
}

function DeploymentGuide({ state }: { state: SelfTestState }) {
  return (
    <div className="self-test-help-content">
      <Alert
        type="info"
        showIcon
        title="在哪里登记绑定？"
        description="部署管理员在运行 FlowTest API 的服务器或容器配置中登记绑定。这里提供配置位置、接入清单和状态检查；“初始化自测”负责接入后的测试资产安装。"
      />
      <Card size="small" title="当前项目接入状态">
        <Descriptions
          size="small"
          column={1}
          items={[
            { key: 'project', label: '项目 ID', children: state.projectId },
            { key: 'binding', label: '自测绑定', children: bindingStatus(state) },
            {
              key: 'harness',
              label: '执行代理（H）',
              children: agentStatus(state.binding?.host_status),
            },
            {
              key: 'observer',
              label: '独立核验代理（O）',
              children: agentStatus(state.binding?.observer_status),
            },
          ]}
        />
      </Card>
      <section>
        <Typography.Title level={4}>1. 准备隔离目标</Typography.Title>
        <Typography.Paragraph>
          由部署管理员准备独立的 FlowTest 被测实例、Mock
          目标和数据、队列、存储隔离，核对实际构建与出站访问许可。
        </Typography.Paragraph>
      </section>
      <section>
        <Typography.Title level={4}>2. 在 API 服务部署配置中登记</Typography.Title>
        <Typography.Paragraph>
          Docker Compose：在 API 服务的 environment 中传入以下配置，再重建该服务。源码或
          Standalone：在启动脚本或服务管理器中设置 API 进程环境变量，再重启 API。
          配置文件需要由启动器显式加载；仅修改宿主机的 .env，不会自动把新增变量传入已有容器。
        </Typography.Paragraph>
        <dl className="self-test-settings-list">
          <dt>
            <code>FLOWTEST_SELFTEST_BINDINGS</code>
          </dt>
          <dd>
            绑定 JSON 数组：填写目标、构建和隔离信息，allowed_project_ids 必须包含上方项目 ID。
          </dd>
          <dt>
            <code>FLOWTEST_SELFTEST_PRINCIPALS</code>
          </dt>
          <dd>代理公钥和权限 JSON 数组：分别登记执行代理与独立核验代理，授权本项目及对应绑定。</dd>
          <dt>
            <code>FLOWTEST_FEATURE_QUALITY_CENTER_ENABLED</code>
          </dt>
          <dd>设为 true，启用质量中心入口。</dd>
        </dl>
      </section>
      <section>
        <Typography.Title level={4}>3. 启动代理并检查接入</Typography.Title>
        <Typography.Paragraph>
          管理员在部署端分别启动执行代理（安装与生成）和独立核验代理（读取证据并核验）。
          完成后点击“重新检查接入”，返回页面选择绑定，再点击“初始化自测”。
        </Typography.Paragraph>
      </section>
      <DeploymentChecklist projectId={state.projectId!} />
    </div>
  )
}

function agentStatus(status: string | undefined): string {
  if (status === undefined) return '尚未核实，请先选择绑定'
  if (status === 'available') return '已登记'
  if (status === 'expired') return '登记已过期，请管理员重新连接'
  return '尚未登记，请管理员启动并连接代理'
}

function DeploymentChecklist({ projectId }: { projectId: string }) {
  const [copyStatus, setCopyStatus] = useState<string | null>(null)
  const request = [
    'FlowTest 自测环境接入清单',
    `项目 ID：${projectId}`,
    '1. 准备独立的 FlowTest 被测实例、Mock 目标及隔离的数据、队列、存储和出站许可。',
    `2. 在 API 服务环境中配置 FLOWTEST_SELFTEST_BINDINGS，allowed_project_ids 包含 ${projectId}，并填写实际目标、构建与隔离身份。`,
    '3. 配置 FLOWTEST_SELFTEST_PRINCIPALS，分别登记执行代理 H 和独立核验代理 O 的公钥、项目/绑定范围及能力。',
    '4. 设置 FLOWTEST_FEATURE_QUALITY_CENTER_ENABLED=true，重启或重建 API，并启动 H/O 代理。',
    '5. 返回“系统自测”，重新检查接入，选择绑定并初始化模板，再创建真实批次。',
    '接入清单只包含项目标识和操作要求；私钥、令牌及密码由部署管理员保管。',
  ].join('\n')
  async function copy() {
    try {
      await navigator.clipboard.writeText(request)
      setCopyStatus('接入清单已复制，可交给部署管理员')
    } catch {
      setCopyStatus('复制失败，请展开下方清单手动复制')
    }
  }
  return (
    <Card size="small" title="交给部署管理员">
      <Space wrap>
        <Button onClick={() => void copy()}>复制项目接入清单</Button>
        <Button href="/help/self-test-setup.md" download="FlowTest-自测部署说明.md">
          下载完整部署说明
        </Button>
      </Space>
      {copyStatus && <Typography.Paragraph role="status">{copyStatus}</Typography.Paragraph>}
      <details className="self-test-deployment-checklist">
        <summary>展开项目接入清单</summary>
        <pre>{request}</pre>
      </details>
    </Card>
  )
}
