import { Alert, Collapse, Empty, Pagination, Space, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { projectPath, type ProjectSection } from '../projects/project-routing'
import type { ServiceTargetImpactPreview, TargetCandidateImpact } from './service-target-service'

type ImpactItem = { id: string; name: string; reason: string; available?: boolean }
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

export default function TargetImpactPanel({
  projectId,
  impact,
  candidate,
}: {
  projectId: string
  impact?: ServiceTargetImpactPreview
  candidate?: TargetCandidateImpact
}) {
  const data = candidate ?? impact
  if (!data) return null
  const complete = candidate?.complete ?? true
  const identity = candidate?.scope_id ?? impact?.service_id
  return (
    <div className="page-alert">
      <Alert
        type="warning"
        showIcon
        title={candidate ? '本次候选的依赖范围' : '保存前请确认下游影响'}
        description={
          candidate
            ? '按本次变更的接口版本、节点服务覆盖、地址变体及计划固定环境分析。流程列表包含草稿和发布版本的潜在引用；计划按实际执行来源筛选。下方单个URL预览不会缩小此范围。历史执行保持原快照，发布策略仅是潜在证据关系。'
            : '以下是逻辑服务的静态引用范围，包含固定历史版本与其他环境；不表示每项会因当前字段变更而改变，也不会改写历史执行。解析预览与连通性检查分别执行。'
        }
      />
      <AnalysisDiagnostics candidate={candidate} />
      <Collapse
        defaultActiveKey={['affected_apis']}
        items={groups.map((group) => ({
          key: group.key,
          label: `${group.label} · ${complete ? '共' : '已识别'} ${data[group.key].length} 项`,
          children: (
            <ImpactGroup
              key={`${identity}:${group.key}`}
              projectId={projectId}
              group={group}
              items={data[group.key]}
              complete={complete}
            />
          ),
        }))}
      />
    </div>
  )
}

function AnalysisDiagnostics({ candidate }: { candidate?: TargetCandidateImpact }) {
  if (!candidate || candidate.complete) return null
  return (
    <Alert
      type="error"
      showIcon
      title="影响范围不完整，数量仅表示已识别结果"
      description={
        <>
          {candidate.diagnostics.map((item, index) => (
            <Typography.Paragraph key={`${item.code}:${index}`}>
              {item.message} · {item.code}
              {item.resource_id && ` · 对象 ${item.resource_id}`}
              {item.node_id && ` · 节点 ${item.node_id}`}
            </Typography.Paragraph>
          ))}
          <Typography.Text type="secondary">追踪 {candidate.trace_id}</Typography.Text>
        </>
      }
    />
  )
}

function ImpactGroup({
  projectId,
  group,
  items,
  complete,
}: {
  projectId: string
  group: Group
  items: ImpactItem[]
  complete: boolean
}) {
  const [page, setPage] = useState(1)
  const start = (page - 1) * 10
  if (!items.length)
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={complete ? '未识别到此类依赖' : '暂未识别到此类依赖，分析尚不完整'}
      />
    )
  return (
    <>
      <Typography.Paragraph type="secondary">
        当前第 {start + 1}–{Math.min(start + 10, items.length)} 项，{complete ? '共' : '已识别'}{' '}
        {items.length} 项
      </Typography.Paragraph>
      <Space orientation="vertical" style={{ width: '100%' }}>
        {items.slice(start, start + 10).map((item) => (
          <div key={item.id} className="request-target-impact-item">
            {item.available === false ? (
              <Typography.Text>{item.name}（已归档或不可用）</Typography.Text>
            ) : (
              <Link
                to={`${projectPath(projectId, group.section)}${group.exact ? `?focus=${encodeURIComponent(item.id)}` : ''}`}
              >
                {group.exact ? item.name : `${item.name}（查看项目发布门禁）`}
              </Link>
            )}
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
