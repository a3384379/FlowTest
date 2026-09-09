import { Descriptions } from 'antd'

type TargetSummary = { url: string; environment: string; source: string }

export default function RequestTargetSummary({ preview }: { preview: unknown }) {
  const summary = targetSummary(preview)
  if (!summary) return null
  return (
    <Descriptions
      size="small"
      column={1}
      items={[
        { key: 'environment', label: '实际环境', children: summary.environment },
        { key: 'url', label: '最终地址', children: summary.url },
        { key: 'source', label: '地址来源', children: summary.source },
      ]}
    />
  )
}

function targetSummary(preview: unknown): TargetSummary | null {
  if (typeof preview !== 'object' || preview === null || !('url' in preview)) return null
  if (typeof preview.url !== 'string') return null
  const target = 'target' in preview ? preview.target : null
  if (typeof target !== 'object' || target === null) return null
  const environment = Reflect.get(target, 'environment_name')
  return {
    url: preview.url,
    environment: typeof environment === 'string' ? environment : '未提供环境快照',
    source: Reflect.get(target, 'endpoint_id') ? '服务 Endpoint' : '环境地址',
  }
}
