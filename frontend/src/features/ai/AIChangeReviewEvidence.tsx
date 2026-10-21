import { Alert, Card, Collapse, Descriptions, Flex, List, Space, Typography } from 'antd'
import { Link } from 'react-router-dom'
import ResponseCodeReader from '../api-console/ResponseCodeReader'
import type { AIChangeItem, AIChangeSetDetail, AIReviewBaseline } from './ai-change-set-service'
import { changeFields, proposedDraft } from './ai-change-diff'

export function AIChangeSource({
  detail,
  projectId,
}: {
  detail: AIChangeSetDetail
  projectId: string
}) {
  return (
    <Card size="small" title="固定来源证据">
      <Descriptions
        column={1}
        size="small"
        items={[
          {
            key: 'fingerprint',
            label: '来源指纹',
            children: (
              <Typography.Text copyable style={{ overflowWrap: 'anywhere' }}>
                {detail.source_fingerprint}
              </Typography.Text>
            ),
          },
          {
            key: 'impact',
            label: '影响分析',
            children: (
              <Link
                to={`/projects/${projectId}/impact?${new URLSearchParams({ focus: detail.impact_run_id })}`}
              >
                {detail.impact_run_id}
              </Link>
            ),
          },
          {
            key: 'risk',
            label: '风险快照',
            children: (
              <Link
                to={`/projects/${projectId}/quality?${new URLSearchParams({ risk: detail.release_risk_id, impact: detail.impact_run_id })}`}
              >
                {detail.release_risk_id}
              </Link>
            ),
          },
          {
            key: 'job',
            label: 'AI 任务',
            children: (
              <Link
                to={`/projects/${projectId}/ai?${new URLSearchParams({ job: detail.ai_job_id })}`}
              >
                {detail.ai_job_id}
              </Link>
            ),
          },
        ]}
      />
      <Typography.Paragraph type="secondary">
        以下材料冻结于生成时；打开来源页面不会替换这份审核证据。
      </Typography.Paragraph>
      <Collapse
        items={[
          {
            key: 'source',
            label: '查看固定来源原文',
            children: <ResponseCodeReader title="固定来源原文" value={detail.source_snapshot} />,
          },
        ]}
      />
    </Card>
  )
}
export function AIChangeBaseline({
  detail,
  item,
  proposed = item.proposed_content,
}: {
  detail: AIChangeSetDetail
  item: AIChangeItem
  proposed?: Record<string, unknown>
}) {
  if (item.action === 'create') return <ResponseCodeReader title="新增草稿内容" value={proposed} />
  const expectedType = item.item_type === 'assertion' ? 'workflow' : item.item_type
  const matches = (detail.review_baselines ?? []).filter(
    (baseline) =>
      baseline.target_id === item.target_resource_id &&
      baseline.target_type === expectedType &&
      baseline.snapshot_sha256 === item.target_snapshot_sha256,
  )
  const baseline = matches.length === 1 ? matches[0] : null
  return (
    <Flex vertical gap={12}>
      <Descriptions
        size="small"
        column={1}
        items={[
          {
            key: 'target',
            label: '目标 ID',
            children: (
              <Typography.Text copyable>{item.target_resource_id ?? '未提供'}</Typography.Text>
            ),
          },
          {
            key: 'hash',
            label: '冻结目标哈希',
            children: (
              <Typography.Text copyable style={{ overflowWrap: 'anywhere' }}>
                {item.target_snapshot_sha256 ?? '未提供'}
              </Typography.Text>
            ),
          },
        ]}
      />
      {baseline ? (
        <FrozenBaseline baseline={baseline} proposed={proposed} />
      ) : (
        <>
          <Alert
            type="warning"
            title="该历史记录未保存可唯一匹配的冻结基线，无法生成可靠差异。"
            description="不会读取当前资产冒充原始基线；接受时仍由服务端核对目标哈希。"
          />
          <ResponseCodeReader title="拟修改内容" value={proposed} />
        </>
      )}
    </Flex>
  )
}
function FrozenBaseline({
  baseline,
  proposed,
}: {
  baseline: AIReviewBaseline
  proposed: Record<string, unknown>
}) {
  const after = proposedDraft(baseline.content, proposed)
  const fields = changeFields(baseline.content, after)
  return (
    <Flex vertical gap={12}>
      <Card size="small" title="冻结目标基线">
        <Typography.Text strong>{baseline.content.name}</Typography.Text>
        <Typography.Paragraph type="secondary">
          草稿修订 {baseline.draft_revision ?? '未提供'} · 版本{' '}
          {baseline.current_version ?? '未发布'} · {baseline.updated_at}
        </Typography.Paragraph>
        <Alert
          type="info"
          title={`生成时数据策略 ${baseline.redaction_mode.toUpperCase()} · v${baseline.redaction_policy_version}`}
          description={
            baseline.redaction_mode === 'on'
              ? '部分值按生成时策略隐藏；目标哈希仍针对当时的完整草稿。差异只比较可读取部分。'
              : '展示生成时冻结的草稿；未替换为当前资产内容。'
          }
        />
      </Card>
      <Card size="small" title={`字段差异 · ${fields.length}`}>
        <List
          dataSource={fields.slice(0, 300)}
          locale={{ emptyText: '可读取字段没有变化' }}
          renderItem={(field) => (
            <List.Item>
              <Flex vertical style={{ minWidth: 0, width: '100%' }} gap={4}>
                <Typography.Text code style={{ overflowWrap: 'anywhere' }}>
                  {field.path}
                </Typography.Text>
                <pre
                  className="code-preview"
                  style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}
                >
                  原值：{JSON.stringify(field.before) ?? '（字段不存在）'}
                  {'\n'}新值：{JSON.stringify(field.after) ?? '（字段不存在）'}
                </pre>
              </Flex>
            </List.Item>
          )}
        />
        {fields.length > 300 ? (
          <Alert type="info" title="仅展开前 300 个差异字段，完整内容见下方原文。" />
        ) : null}
      </Card>
      <Collapse
        items={[
          {
            key: 'before',
            label: '冻结基线完整内容',
            children: <ResponseCodeReader title="冻结基线完整内容" value={baseline.content} />,
          },
          {
            key: 'after',
            label: '拟写入草稿完整内容',
            children: <ResponseCodeReader title="拟写入草稿完整内容" value={after} />,
          },
        ]}
      />
    </Flex>
  )
}
export function AIChangeReviewReceipt({
  item,
  projectId,
}: {
  item: AIChangeItem
  projectId: string
}) {
  if (item.review_status === 'pending') return null
  return (
    <Flex vertical gap={8}>
      <Descriptions
        column={1}
        size="small"
        items={[
          { key: 'by', label: '审核人', children: item.reviewed_by_id ?? '未提供' },
          { key: 'at', label: '审核时间', children: item.reviewed_at ?? '未提供' },
          { key: 'note', label: '审核备注', children: item.review_note || '未填写' },
        ]}
      />
      {item.review_status === 'accepted' ? (
        <MaterializedDraft item={item} projectId={projectId} />
      ) : null}
    </Flex>
  )
}
function MaterializedDraft({ item, projectId }: { item: AIChangeItem; projectId: string }) {
  const id = item.materialized_resource_id,
    type = item.materialized_resource_type
  if (!id) return <Alert type="info" title="审核记录已保存，未返回可定位的草稿 ID。" />
  const routes = {
    workflow: { section: 'workflows', label: '打开流程草稿', query: { focus: id } },
    test_case: {
      section: 'assets',
      label: '打开用例草稿',
      query: { type: 'case', focus: id, version: 'draft' },
    },
  }
  const target = type === 'workflow' || type === 'test_case' ? routes[type] : null
  return (
    <Space wrap>
      {target ? (
        <Link to={`/projects/${projectId}/${target.section}?${new URLSearchParams(target.query)}`}>
          {target.label}
        </Link>
      ) : (
        <Typography.Text>未识别的资产类型：{type ?? '未提供'}</Typography.Text>
      )}
      <Typography.Text copyable style={{ overflowWrap: 'anywhere' }}>
        {id}
      </Typography.Text>
      <Typography.Text type="secondary">仅更新草稿；未发布、未执行。</Typography.Text>
    </Space>
  )
}
