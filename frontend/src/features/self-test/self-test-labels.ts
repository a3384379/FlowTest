export const generationModeLabels = {
  deterministic_mcp: '确定性 MCP · 无 LLM',
  host_llm_mcp: '真实宿主 + Skill + 模型',
} as const
export const readinessLabels = {
  ready: '准备条件已满足',
  needs_input: '待补输入',
  needs_review: '待人工审核',
  unsupported: '不支持',
  blocked: '已阻断',
} as const
export const phaseLabels: Record<string, string> = {
  pending: '待调度',
  generating: '正在生成',
  running: '正式执行',
  collecting: '正在收集证据',
  expired: '已过期',
  preflight: '安全预检',
  installing: '正在初始化',
  executing: '正式执行',
  verifying: '独立核验',
  cleaning: '正在清理',
  completed: '已结束',
  cancelled: '已取消',
  discovering: '契约发现',
  reading_contract: '读取契约',
  designing: '设计生成',
  compiling: '编译',
  proposing: '流程提案',
  awaiting_review: '待人工审核',
  publishing: '待发布固定版本',
  ready: '已就绪',
  blocked: '已阻断',
}

const reasonLabels = {
  WAITING_FOR_HOST: '任务已创建，等待已授权外部宿主认领',
  SELFTEST_HOST_NOT_REGISTERED: '尚未登记有效外部宿主',
  SELFTEST_OBSERVER_NOT_CONFIGURED: '尚未配置独立 Observer',
  SELFTEST_EXECUTION_NOT_READY: '固定版本或执行来源尚未就绪',
  SELFTEST_INSTALLATION_NOT_READY: '隔离资源尚未安装就绪',
  SELFTEST_PREVIEW_EXPIRED: '预检已过期，请重新预检',
  SELFTEST_PREVIEW_CHANGED: '预检输入或资源状态已变化',
  SELFTEST_INSTALLATION_BINDING_CHANGED: '安装绑定发生变化',
  SELFTEST_INSTALLATION_CONFLICT: '隔离资源存在冲突',
  SELFTEST_BINDING_UNSAFE: '绑定未满足隔离目标要求',
  SELFTEST_FULL_PACK_INCOMPLETE: '冻结包必需场景尚未齐全',
  SELFTEST_CANCEL_REQUESTED: '已请求取消，等待停止与清理证据',
  SELFTEST_DISPATCH_UNCONFIRMED: '队列派发结果待确认，可恢复原运行派发',
  SELFTEST_BATCH_EXPIRED: '批次已超过冻结截止时间',
  SELFTEST_WATCHDOG_CANCEL_REQUESTED: '截止清理已请求取消原运行',
  SELFTEST_EVIDENCE_EXPIRED: '原始证据已删除或过期，当前验收已阻断',
  SELFTEST_EVIDENCE_UNAVAILABLE: '暂时无法核实原始证据可用性，当前验收已阻断',
  SELFTEST_RECURSION_LIMIT_REACHED: '业务夹具实例已达到自测递归深度上限',
} as const
export function selfTestReasonLabel(reason: string) {
  if (reason in reasonLabels)
    return `${reasonLabels[reason as keyof typeof reasonLabels]}（${reason}）`
  return reason
}

export const installationStatusLabels = {
  needs_input: '待外部宿主处理',
  queued: '已排队',
  installing: '正在初始化',
  ready: '已就绪',
  blocked: '已阻断',
  archived: '已归档',
} as const

export const runtimeProfileLabels = {
  full: '完整部署',
  compose: 'Compose 部署',
  standalone: '独立部署',
  compact: '紧凑部署',
} as const

export const previewCheckLabels = { passed: '通过', blocked: '阻断', warning: '需注意' } as const
export const previewResourceLabels = {
  environment: '环境',
  service: '服务',
  api: '接口',
  workflow: '工作流',
  case: '测试用例',
  suite: '测试套件',
  plan: '测试计划',
} as const
export const previewActionLabels = { create: '创建', reuse: '复用', conflict: '冲突' } as const

export const verdictLabels = {
  pending: '待核验',
  passed: '通过',
  failed: '失败',
  blocked: '已阻断',
} as const
