import { Alert, Collapse, Empty, Pagination, Space, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useProjectContext } from '../projects/use-project-context'
import { projectPath, type ProjectSection } from '../projects/project-routing'
import type { ServiceTargetImpactPreview } from './service-target-service'

type ImpactItem = { id: string; name: string; reason: string }
type Group = {
  key: keyof Pick<
    ServiceTargetImpactPreview,
    | 'affected_apis'
    | 'affected_workflows'
    | 'affected_test_plans'
    | 'affected_scheduled_runs'
    | 'affected_release_gates'
  >
  label: string
  section: ProjectSection
  exact: boolean
}
const groups: readonly Group[] = [
  { key: 'affected_apis', label: '接口', section: 'apis', exact: true },
  { key: 'affected_workflows', label: '流程', section: 'workflows', exact: true },
  { key: 'affected_test_plans', label: '测试计划', section: 'tasks', exact: true },
  { key: 'affected_scheduled_runs', label: '定时计划', section: 'tasks', exact: true },
  { key: 'affected_release_gates', label: '潜在发布策略', section: 'release', exact: false },
]

export default function TargetImpactPanel({ impact }: { impact?: ServiceTargetImpactPreview }) {
  const { projectId } = useProjectContext()
  if (!impact || !projectId) return null
  return (
    <div className="page-alert">
      <Alert
        type="warning"
        showIcon
        title="保存前请确认下游影响"
        description="以下是逻辑服务的静态引用范围，包含固定历史版本与其他环境；不表示每项会因当前字段变更而改变，也不会改写历史执行。解析预览与连通性检查分别执行。"
      />
      <Collapse
        defaultActiveKey={['affected_apis']}
        items={groups.map((group) => ({
          key: group.key,
          label: `${group.label} · 共 ${impact[group.key].length} 项`,
          children: (
            <ImpactGroup
              key={`${impact.service_id}:${group.key}`}
              projectId={projectId}
              group={group}
              items={impact[group.key]}
            />
          ),
        }))}
      />
    </div>
  )
}

function ImpactGroup({
  projectId,
  group,
  items,
}: {
  projectId: string
  group: Group
  items: ImpactItem[]
}) {
  const [page, setPage] = useState(1)
  const start = (page - 1) * 10
  if (!items.length)
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有查到直接引用" />
  return (
    <>
      <Typography.Paragraph type="secondary">
        当前第 {start + 1}–{Math.min(start + 10, items.length)} 项，共 {items.length} 项
      </Typography.Paragraph>
      <Space orientation="vertical" style={{ width: '100%' }}>
        {items.slice(start, start + 10).map((item) => (
          <div key={item.id} className="request-target-impact-item">
            <Link
              to={`${projectPath(projectId, group.section)}${group.exact ? `?focus=${encodeURIComponent(item.id)}` : ''}`}
            >
              {group.exact ? item.name : `${item.name}（查看项目发布门禁）`}
            </Link>
            <Typography.Paragraph copyable style={{ marginBottom: 4 }}>
              {item.id}
            </Typography.Paragraph>
            <Typography.Text type="secondary">{item.reason}</Typography.Text>
          </div>
        ))}
      </Space>
      <Pagination
        current={page}
        pageSize={10}
        total={items.length}
        hideOnSinglePage
        showSizeChanger={false}
        onChange={setPage}
      />
    </>
  )
}
