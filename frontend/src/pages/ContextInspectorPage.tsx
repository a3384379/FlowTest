import { ArrowRightOutlined, FileSearchOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Flex,
  List,
  Row,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { Link } from 'react-router-dom'

import type {
  ContextDetail,
  ContextEvidenceItem,
  ContextProposal,
  ContextStatus,
  EvidenceProviderType,
  KnowledgeNode,
} from '../features/context-inspector/context-inspector-service'
import { useContextInspector } from '../features/context-inspector/use-context-inspector'
import { projectPath } from '../features/projects/project-routing'
import { apiErrorMessage } from '../lib/api'

export default function ContextInspectorPage() {
  const state = useContextInspector()
  return (
    <>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>上下文检查器</Typography.Title>
          <Typography.Text type="secondary">
            查看 Context Revision、Evidence、冲突、State Knowledge 与关联 Flow Proposal。
          </Typography.Text>
        </div>
      </div>
      <Alert
        showIcon
        type="info"
        icon={<FileSearchOutlined />}
        title="只读检查界面：不扩大 MCP 权限，不修改 Evidence，不自动接受或应用 Proposal。"
        style={{ marginBottom: 16 }}
      />
      {state.contexts.isError ? (
        <Alert type="error" showIcon title={apiErrorMessage(state.contexts.error)} />
      ) : (
        <Row gutter={16}>
          <Col span={7}>
            <ContextList state={state} />
          </Col>
          <Col span={17}>
            <Card title="Context Detail" loading={state.detail.isLoading}>
              {state.detail.isError ? (
                <Alert type="error" showIcon title={apiErrorMessage(state.detail.error)} />
              ) : (
                <ContextDetailView detail={state.detail.data} projectId={state.projectId} />
              )}
            </Card>
          </Col>
        </Row>
      )}
    </>
  )
}

type InspectorState = ReturnType<typeof useContextInspector>

function ContextList({ state }: { state: InspectorState }) {
  const items = state.contexts.data?.items ?? []
  return (
    <Card
      title={`Context List · ${state.contexts.data?.total ?? 0}`}
      loading={state.contexts.isLoading}
    >
      {items.length === 0 && !state.contexts.isLoading ? (
        <Empty description="暂无 Test Context" />
      ) : (
        <Flex vertical gap={8}>
          {items.map((item) => (
            <Button
              key={item.id}
              type={item.id === state.activeId ? 'primary' : 'text'}
              ghost={item.id === state.activeId}
              block
              onClick={() => state.select(item.id)}
              style={{ height: 'auto', padding: 12, textAlign: 'left' }}
            >
              <Flex vertical align="flex-start" gap={4}>
                <Typography.Text strong>{item.name}</Typography.Text>
                <Space size={4} wrap>
                  <StatusTag status={item.status} />
                  <Tag>Revision {item.current_revision}</Tag>
                  {item.completeness.missing.length ? (
                    <Tag color="warning">缺失 {item.completeness.missing.length}</Tag>
                  ) : null}
                  {item.conflict_count ? <Tag color="error">冲突 {item.conflict_count}</Tag> : null}
                </Space>
              </Flex>
            </Button>
          ))}
        </Flex>
      )}
    </Card>
  )
}

function ContextDetailView({
  detail,
  projectId,
}: {
  detail: ContextDetail | undefined
  projectId: string | null
}) {
  if (!detail) return <Empty description="选择 Context 查看当前 Revision" />
  return (
    <Flex vertical gap={16}>
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="名称">{detail.name}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <StatusTag status={detail.status} />
        </Descriptions.Item>
        <Descriptions.Item label="目标" span={2}>
          {detail.objective}
        </Descriptions.Item>
        <Descriptions.Item label="Revision">{detail.current_revision}</Descriptions.Item>
        <Descriptions.Item label="Fingerprint">
          <Typography.Text code>{detail.revision_fingerprint.slice(0, 16)}</Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="Evidence">{detail.evidence_count}</Descriptions.Item>
        <Descriptions.Item label="Provider">{detail.provider_count}</Descriptions.Item>
        <Descriptions.Item label="关联 Proposal">{detail.proposal_count}</Descriptions.Item>
        <Descriptions.Item label="过期时间">
          {new Date(detail.expires_at).toLocaleString()}
        </Descriptions.Item>
      </Descriptions>
      <Completeness detail={detail} />
      <Conflicts detail={detail} />
      <ProviderSummary detail={detail} />
      <EvidenceFindings items={detail.evidence_items} />
      <Knowledge detail={detail} />
      <Proposals items={detail.proposals} projectId={projectId} />
    </Flex>
  )
}

function Completeness({ detail }: { detail: ContextDetail }) {
  const completeness = detail.revision.completeness
  return (
    <Card size="small" title="Evidence Completeness">
      <Flex vertical gap={8}>
        <Space wrap>
          <Typography.Text type="secondary">必需：</Typography.Text>
          {completeness.required.map((item) => (
            <Tag key={item}>{providerLabel(item)}</Tag>
          ))}
        </Space>
        <Space wrap>
          <Typography.Text type="secondary">已有：</Typography.Text>
          {completeness.present.map((item) => (
            <Tag color="success" key={item}>
              {providerLabel(item)}
            </Tag>
          ))}
        </Space>
        {completeness.missing.length ? (
          <Alert
            type="warning"
            showIcon
            title={`缺少 Evidence：${completeness.missing.map(providerLabel).join('、')}`}
          />
        ) : (
          <Alert type="success" showIcon title="当前 Revision 已满足必需 Evidence" />
        )}
      </Flex>
    </Card>
  )
}

function Conflicts({ detail }: { detail: ContextDetail }) {
  const conflicts = detail.revision.conflict_snapshot.conflicts
  return (
    <Card size="small" title={`Evidence Conflict · ${conflicts.length}`}>
      {conflicts.length === 0 ? (
        <Typography.Text type="secondary">当前 Revision 无冲突。</Typography.Text>
      ) : (
        <List
          dataSource={conflicts}
          renderItem={(item) => (
            <List.Item>
              <List.Item.Meta title={item.summary} description={item.subject_ref} />
            </List.Item>
          )}
        />
      )}
    </Card>
  )
}

function ProviderSummary({ detail }: { detail: ContextDetail }) {
  return (
    <Card size="small" title="Provider Summary">
      <Table
        size="small"
        pagination={false}
        rowKey={(item) => `${item.source_type}:${item.provider_name}:${item.provider_version}`}
        dataSource={detail.providers}
        columns={[
          {
            title: 'Provider',
            render: (_, item) => `${item.provider_name} ${item.provider_version}`,
          },
          { title: '类型', dataIndex: 'source_type', render: providerLabel },
          { title: 'Finding', dataIndex: 'finding_count' },
          { title: '确定性', dataIndex: 'deterministic_count' },
          { title: '冲突', dataIndex: 'conflict_count' },
        ]}
      />
    </Card>
  )
}

function EvidenceFindings({ items }: { items: ContextEvidenceItem[] }) {
  return (
    <Card size="small" title={`Provider Finding · ${items.length}`}>
      {items.length === 0 ? (
        <Empty description="当前 Revision 暂无 Finding" />
      ) : (
        <List
          dataSource={items}
          renderItem={(item) => (
            <List.Item>
              <List.Item.Meta
                title={
                  <Space wrap>
                    <Typography.Text strong>{item.finding.statement}</Typography.Text>
                    <Tag>{item.finding.kind}</Tag>
                    <Tag color={item.deterministic ? 'success' : 'warning'}>
                      {item.deterministic ? '确定性' : '需复核'}
                    </Tag>
                  </Space>
                }
                description={
                  <Flex vertical gap={4}>
                    <Typography.Text type="secondary">
                      {item.provider_name} {item.provider_version} · {item.finding.source_path}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      {item.source_ref}@{item.source_revision} · confidence {item.confidence}
                    </Typography.Text>
                    {item.warnings.map((warning) => (
                      <Alert
                        key={`${item.id}:${warning.code}`}
                        type="warning"
                        showIcon
                        title={`${warning.code}：${warning.message}`}
                      />
                    ))}
                  </Flex>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Card>
  )
}

function Knowledge({ detail }: { detail: ContextDetail }) {
  const knowledge = detail.revision.knowledge_snapshot
  const labels = new Map(knowledge.nodes.map((node) => [node.id, node.label]))
  const states = knowledge.nodes.filter((node) => node.kind === 'state_candidate')
  return (
    <Card
      size="small"
      title={`State Knowledge · ${knowledge.nodes.length} Nodes / ${knowledge.edges.length} Edges`}
    >
      <Typography.Title level={5}>State Candidate</Typography.Title>
      <KnowledgeNodes nodes={states} />
      <Typography.Title level={5}>Knowledge Graph</Typography.Title>
      <Table
        size="small"
        pagination={{ pageSize: 8, hideOnSinglePage: true }}
        rowKey={(item) => `${item.source}:${item.relation}:${item.target}`}
        dataSource={knowledge.edges}
        columns={[
          { title: '源', dataIndex: 'source', render: (value) => labels.get(value) ?? value },
          { title: '关系', dataIndex: 'relation', render: (value) => <Tag>{value}</Tag> },
          { title: '目标', dataIndex: 'target', render: (value) => labels.get(value) ?? value },
        ]}
      />
    </Card>
  )
}

function KnowledgeNodes({ nodes }: { nodes: KnowledgeNode[] }) {
  if (nodes.length === 0) return <Empty description="暂无 State Candidate" />
  return (
    <Table
      size="small"
      pagination={false}
      rowKey="id"
      dataSource={nodes}
      columns={[
        { title: '候选状态', dataIndex: 'label' },
        {
          title: 'Evidence Ref',
          render: (_, node) =>
            node.facts
              .filter((fact) => fact.name === 'evidence_ref')
              .map((fact) => fact.value)
              .join('、') || '-',
        },
        {
          title: '复核',
          render: (_, node) =>
            node.facts.some((fact) => fact.name === 'requires_review' && fact.value === 'true') ? (
              <Tag color="warning">需复核</Tag>
            ) : (
              <Tag color="success">已确定</Tag>
            ),
        },
      ]}
    />
  )
}

function Proposals({ items, projectId }: { items: ContextProposal[]; projectId: string | null }) {
  return (
    <Card size="small" title={`Flow Proposal · ${items.length}`}>
      {items.length === 0 ? (
        <Empty description="当前 Revision 暂无关联 Proposal" />
      ) : (
        <Table
          size="small"
          pagination={false}
          rowKey="id"
          dataSource={items}
          columns={[
            { title: '名称', dataIndex: 'title' },
            { title: '审核', dataIndex: 'review_status', render: proposalReviewLabel },
            {
              title: '应用',
              dataIndex: 'applied',
              render: (value) => (
                <Tag color={value ? 'success' : 'default'}>{value ? '已应用' : '未应用'}</Tag>
              ),
            },
            {
              title: '操作',
              render: (_, item) =>
                projectId ? (
                  <Link to={`${projectPath(projectId, 'workflows')}?proposal=${item.id}`}>
                    打开 Proposal <ArrowRightOutlined />
                  </Link>
                ) : null,
            },
          ]}
        />
      )}
    </Card>
  )
}

function StatusTag({ status }: { status: ContextStatus }) {
  const colors: Record<ContextStatus, string> = {
    collecting: 'processing',
    ready: 'success',
    incomplete: 'warning',
    conflicted: 'error',
    expired: 'default',
    closed: 'default',
  }
  const labels: Record<ContextStatus, string> = {
    collecting: '采集中',
    ready: '就绪',
    incomplete: '不完整',
    conflicted: '有冲突',
    expired: '已过期',
    closed: '已关闭',
  }
  return <Tag color={colors[status]}>{labels[status]}</Tag>
}

function providerLabel(value: EvidenceProviderType): string {
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
  return labels[value]
}

function proposalReviewLabel(value: ContextProposal['review_status']) {
  const label = value === 'accepted' ? '已接受' : value === 'rejected' ? '已拒绝' : '待审核'
  const color = value === 'accepted' ? 'success' : value === 'rejected' ? 'default' : 'warning'
  return <Tag color={color}>{label}</Tag>
}
