import type { EvidenceProviderType } from './context-inspector-service'
export function providerTypeLabel(value: EvidenceProviderType): string {
  const labels: Record<EvidenceProviderType, string> = {
    repository: '仓库',
    contract: '契约',
    data_profile: '数据画像',
    service_topology: '服务拓扑',
    existing_test: '已有测试',
    workflow: '工作流',
    runtime: '运行时',
    change: '变更',
    user_confirmed_rule: '人工规则',
    database: '数据库',
  }
  return labels[value] ?? value
}
