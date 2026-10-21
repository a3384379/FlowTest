import { Alert, Collapse, Descriptions, Space, Table, Typography } from 'antd'
import { Link } from 'react-router-dom'

import ResponseCodeReader from '../api-console/ResponseCodeReader'
import { confidenceLabel } from '../test-engineering/design-confidence'
import type { MCPChangeItem } from './mcp-change-set-service'

type Content = Record<string, unknown>

export default function MCPStructuredPreview({
  item,
  projectId,
}: {
  item: MCPChangeItem
  projectId: string
}) {
  if (item.item_type === 'test_design') return <DesignPreview content={item.proposed_content} />
  if (item.item_type === 'test_case')
    return <CasePreview content={item.proposed_content} projectId={projectId} />
  if (item.item_type === 'test_plan_update')
    return <PlanPreview content={item.proposed_content} projectId={projectId} />
  return null
}

export function DesignPreview({ content }: { content: Content }) {
  const intent = record(content.intent)
  return (
    <Space orientation="vertical" className="full-width">
      <Typography.Title level={5}>测试设计预览</Typography.Title>
      <Descriptions
        column={1}
        items={[
          { label: '意图标识', children: display(intent.key) },
          { label: '设计目标', children: display(intent.objective) },
          { label: '设计置信度', children: confidenceLabel(content.confidence) },
          {
            label: '验收条件',
            children: <ValueList value={intent.acceptance_criteria} empty="未声明验收条件" />,
          },
          {
            label: '审核要求',
            children: <ValueList value={content.review_requirements} empty="未声明额外审核要求" />,
          },
        ]}
      />
      <ReadTable
        title="场景"
        value={content.scenarios}
        columns={[
          { title: '名称', dataIndex: 'title', render: display },
          { title: '预期分类', dataIndex: 'expected_category', render: display },
          { title: '置信度', dataIndex: 'confidence', render: confidenceLabel },
          { title: '来源引用', dataIndex: 'evidence_refs', render: display },
        ]}
      />
      <ReadTable
        title="预期与断言"
        value={content.oracles}
        columns={[
          { title: '类型', dataIndex: 'kind', render: display },
          { title: '表达式', dataIndex: 'expression', render: display },
          { title: '比较', dataIndex: 'operator', render: display },
          { title: '预期值', dataIndex: 'expected', render: display },
          { title: '置信度', dataIndex: 'confidence', render: confidenceLabel },
          { title: '来源引用', dataIndex: 'evidence_refs', render: display },
        ]}
      />
      <ReadTable
        title="覆盖内容"
        value={record(content.coverage).entries}
        columns={[
          { title: '目标', dataIndex: 'target_ref', render: display },
          { title: '要求', dataIndex: 'requirement', render: display },
          { title: '覆盖状态', dataIndex: 'covered', render: booleanLabel },
          { title: '原因', dataIndex: 'reason', render: display },
        ]}
      />
      <ReadTable
        title="设计来源证据"
        value={content.evidence_refs}
        columns={[
          { title: '引用', dataIndex: 'id', render: display },
          { title: '类型', dataIndex: 'source_type', render: display },
          { title: '来源', dataIndex: 'source_ref', render: display },
          { title: '修订', dataIndex: 'revision', render: display },
        ]}
      />
      <ValueList value={content.warnings} empty="此设计没有附加警告" />
      <Collapse
        items={[
          {
            key: 'models',
            label: '知识图谱与状态模型',
            children: (
              <ResponseCodeReader
                title="设计模型"
                value={{
                  knowledge_graph: content.knowledge_graph,
                  state_model: content.state_model,
                }}
              />
            ),
          },
        ]}
      />
    </Space>
  )
}

function CasePreview({ content, projectId }: { content: Content; projectId: string }) {
  const definition = record(content.definition)
  return (
    <Space orientation="vertical" className="full-width">
      <Typography.Title level={5}>测试用例预览</Typography.Title>
      <Descriptions
        column={1}
        items={[
          { label: '名称', children: display(content.name) },
          { label: '说明', children: display(content.description) },
          { label: '标签', children: display(content.tags) },
          {
            label: '引用工作流',
            children: (
              <AssetReference projectId={projectId} kind="workflow" id={definition.workflow_id} />
            ),
          },
          {
            label: '工作流版本',
            children:
              definition.workflow_version === null
                ? '未固定，发布时需确认'
                : display(definition.workflow_version),
          },
          { label: '环境', children: display(definition.environment_id) },
        ]}
      />
      <Typography.Text type="secondary">
        断言沿用所引用工作流；此用例提案没有独立断言定义。
      </Typography.Text>
      <Collapse
        items={[
          {
            key: 'runtime',
            label: '用例运行参数',
            children: (
              <ResponseCodeReader
                title="用例运行参数"
                value={{
                  runtime_variables: definition.runtime_variables,
                  runtime_headers: definition.runtime_headers,
                }}
              />
            ),
          },
        ]}
      />
    </Space>
  )
}

function PlanPreview({ content, projectId }: { content: Content; projectId: string }) {
  const targets = contentRows(content.targets)
  const actions = contentRows(content.target_actions)
  return (
    <Space orientation="vertical" className="full-width">
      <Typography.Title level={5}>测试计划更新预览</Typography.Title>
      <Descriptions
        column={1}
        items={[
          {
            label: '目标计划',
            children:
              typeof content.test_plan_id === 'string' ? (
                <Link
                  to={`/projects/${projectId}/tasks?focus=${encodeURIComponent(content.test_plan_id)}`}
                >
                  {content.test_plan_id}
                </Link>
              ) : (
                '未提供'
              ),
          },
          { label: '变更依据', children: display(content.rationale) },
          {
            label: '未发布依赖',
            children: <ValueList value={content.unpublished_dependencies} empty="无未发布依赖" />,
          },
        ]}
      />
      <Alert
        type="info"
        showIcon
        title="计划提案未保存原环境、重试及运行参数；仅下表中的原版本和指纹可作变更前证据"
        description="此表覆盖提案涉及的目标，未包含计划的完整原项列表。"
      />
      {actions !== null && !actions.length && (
        <Alert
          type="warning"
          title="未提供逐项目操作快照；旧提案按新增建议处理，接受时仍由服务端校验"
        />
      )}
      {actions === null && (
        <Alert type="warning" title="逐项目操作快照未提供或结构无效，不能据此判断新增或更新" />
      )}
      {targets === null ? (
        <Typography.Text>目标列表未提供或结构无效，请核对完整提案。</Typography.Text>
      ) : (
        <Table
          rowKey={(_, index) => String(index)}
          size="small"
          dataSource={targets}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          scroll={{ x: 1000 }}
          columns={[
            {
              title: '目标',
              render: (_, target) => (
                <AssetReference
                  projectId={projectId}
                  kind={target.target_type}
                  id={target.target_id}
                />
              ),
            },
            { title: '操作', render: (_, target) => display(findAction(actions, target)?.action) },
            {
              title: '版本（原 → 拟）',
              render: (_, target) => versionChange(findAction(actions, target), target),
            },
            { title: '拟用环境', dataIndex: 'environment_id', render: display },
            { title: '拟用重试上限', dataIndex: 'max_retries', render: display },
            {
              title: '原指纹',
              render: (_, target) => (
                <CopyValue value={findAction(actions, target)?.current_fingerprint} />
              ),
            },
            {
              title: '拟用指纹',
              render: (_, target) => (
                <CopyValue value={findAction(actions, target)?.requested_fingerprint} />
              ),
            },
            { title: '原因', render: (_, target) => display(findAction(actions, target)?.reason) },
          ]}
          expandable={{
            expandedRowRender: (target) => (
              <ResponseCodeReader title="拟用目标完整参数" value={target} />
            ),
          }}
        />
      )}
    </Space>
  )
}

function ReadTable({
  title,
  value,
  columns,
}: {
  title: string
  value: unknown
  columns: import('antd').TableColumnsType<Content>
}) {
  const rows = contentRows(value)
  return (
    <section aria-label={title}>
      <Typography.Title level={5}>{title}</Typography.Title>
      {rows === null ? (
        <Typography.Text>{title}未提供或结构无效，请核对完整提案。</Typography.Text>
      ) : (
        <Table
          rowKey={(_, index) => String(index)}
          size="small"
          dataSource={rows}
          columns={columns}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          scroll={{ x: 750 }}
          locale={{ emptyText: `此提案没有${title}` }}
        />
      )}
    </section>
  )
}

function ValueList({ value, empty }: { value: unknown; empty: string }) {
  if (!Array.isArray(value)) return <Typography.Text>未提供</Typography.Text>
  if (!value.length) return <Typography.Text type="secondary">{empty}</Typography.Text>
  return (
    <ul>
      {value.map((item, index) => (
        <li key={index}>{display(item)}</li>
      ))}
    </ul>
  )
}

function AssetReference({
  projectId,
  kind,
  id,
}: {
  projectId: string
  kind: unknown
  id: unknown
}) {
  if (typeof id !== 'string' || !id) return <>未提供</>
  const encoded = encodeURIComponent(id)
  if (kind === 'workflow')
    return <Link to={`/projects/${projectId}/workflows?focus=${encoded}`}>{id}</Link>
  if (kind === 'case' || kind === 'suite')
    return <Link to={`/projects/${projectId}/assets?type=${kind}&focus=${encoded}`}>{id}</Link>
  return <Typography.Text>{id}（类型未识别）</Typography.Text>
}
function CopyValue({ value }: { value: unknown }) {
  return typeof value === 'string' ? (
    <Typography.Text copyable style={{ overflowWrap: 'anywhere' }}>
      {value}
    </Typography.Text>
  ) : (
    <>未提供</>
  )
}
function findAction(actions: Content[] | null, target: Content): Content | undefined {
  return actions?.find(
    (action) => action.target_id === target.target_id && action.target_type === target.target_type,
  )
}
function versionChange(action: Content | undefined, target: Content): string {
  return `${display(action?.current_version)} → ${display(action?.requested_version ?? target.target_version ?? target.workflow_version)}`
}
function record(value: unknown): Content {
  return isRecord(value) ? value : {}
}
function isRecord(value: unknown): value is Content {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function contentRows(value: unknown): Content[] | null {
  return Array.isArray(value) && value.every(isRecord) ? value : null
}
function booleanLabel(value: unknown): string {
  return typeof value === 'boolean' ? (value ? '已覆盖' : '未覆盖') : '未提供'
}
function display(value: unknown): string {
  if (value === undefined || value === null) return '未提供'
  return typeof value === 'string' ? value : JSON.stringify(value)
}
