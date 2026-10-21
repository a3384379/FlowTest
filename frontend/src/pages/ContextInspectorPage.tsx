import { ArrowRightOutlined, FileSearchOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Flex,
  Row,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { Link, useSearchParams } from 'react-router-dom'

import type {
  ContextDetail,
  ContextProposal,
  ContextStatus,
} from '../features/context-inspector/context-inspector-service'
import { useContextInspector } from '../features/context-inspector/use-context-inspector'
import ContextPageControls from '../features/context-inspector/ContextPageControls'
import { projectPath } from '../features/projects/project-routing'
import { apiErrorWithTrace } from '../lib/api'
import ContextEvidenceBrowser from '../features/context-inspector/ContextEvidenceBrowser'
import { providerTypeLabel as providerLabel } from '../features/context-inspector/context-presentation'
import ContextKnowledgePanel from '../features/context-inspector/ContextKnowledgePanel'
import type { ContextPanel } from '../features/context-inspector/context-navigation'

export default function ContextInspectorPage() {
  const [searchParams] = useSearchParams()
  const state = useContextInspector(searchParams.get('focus') ?? undefined)
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
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={7} style={{ minWidth: 0 }}>
          <ContextList state={state} />
        </Col>
        <Col xs={24} lg={17} style={{ minWidth: 0 }}>
          <section aria-label="上下文详情">
            <ContextDetailState state={state} />
          </section>
        </Col>
      </Row>
    </>
  )
}

type InspectorState = ReturnType<typeof useContextInspector>

function ContextList({ state }: { state: InspectorState }) {
  const items = state.contexts.isSuccess ? state.contexts.data.items : []
  return (
    <Card
      title={`Context List · ${state.contexts.isSuccess ? state.contexts.data.total : '未提供'}`}
      loading={state.contexts.isLoading}
    >
      {state.contexts.isError ? (
        <Alert
          type="error"
          title={apiErrorWithTrace(state.contexts.error)}
          action={<Button onClick={() => void state.contexts.refetch()}>重试目录</Button>}
        />
      ) : null}
      {items.length === 0 && !state.contexts.isLoading && !state.contexts.isError ? (
        <Empty description="暂无 Test Context" />
      ) : (
        <Flex vertical gap={8} style={{ maxHeight: 380, overflowY: 'auto' }}>
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
      <ContextPageControls
        page={state.page}
        total={state.contexts.data?.total ?? 0}
        onChange={state.setPage}
      />
    </Card>
  )
}

function ContextDetailState({ state }: { state: InspectorState }) {
  if (state.detail.isError)
    return (
      <Alert
        type="error"
        showIcon
        title={apiErrorWithTrace(state.detail.error)}
        action={<Button onClick={() => void state.detail.refetch()}>重试详情</Button>}
      />
    )
  if (!state.detail.isSuccess) return <Empty description="选择 Context 查看当前 Revision" />
  if (state.revisionMismatch)
    return (
      <Alert
        type="warning"
        showIcon
        title="所选固定修订不可读取"
        description={`所选 ${state.expectedRevision}；当前接口返回 ${state.detail.data.revision_id}。该接口仅提供当前修订，不会将新修订冒充旧修订。`}
        action={<Button onClick={state.showCurrentRevision}>查看当前修订</Button>}
      />
    )
  return (
    <ContextDetailView
      key={`${state.detail.data.id}:${state.detail.data.revision_id}`}
      detail={state.detail.data}
      state={state}
    />
  )
}
function ContextDetailView({ detail, state }: { detail: ContextDetail; state: InspectorState }) {
  const props = { detail, selection: state.selection, onNavigate: state.navigate }
  return (
    <Flex vertical gap={16}>
      <Typography.Paragraph>
        当前 Revision {detail.current_revision} ·{' '}
        <Typography.Text copyable>{detail.revision_id}</Typography.Text>
      </Typography.Paragraph>
      {detail.status === 'expired' ? (
        <Alert type="warning" title="该上下文已过期，仅用于只读回看。" />
      ) : null}
      <Tabs
        activeKey={state.selection.panel}
        destroyOnHidden
        onChange={(key) => state.navigate({ panel: key as ContextPanel })}
        items={[
          {
            key: 'overview',
            label: '概要',
            children: (
              <>
                {' '}
                <Descriptions bordered size="small" column={{ xs: 1, md: 2 }}>
                  <Descriptions.Item label="名称">{detail.name}</Descriptions.Item>
                  <Descriptions.Item label="状态">
                    <StatusTag status={detail.status} />
                  </Descriptions.Item>
                  <Descriptions.Item label="目标" span={{ xs: 1, md: 2 }}>
                    {detail.objective}
                  </Descriptions.Item>
                  <Descriptions.Item label="Revision">{detail.current_revision}</Descriptions.Item>
                  <Descriptions.Item label="Fingerprint">
                    <Typography.Text code copyable={{ text: detail.revision_fingerprint }}>
                      {detail.revision_fingerprint.slice(0, 16)}…
                    </Typography.Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="Evidence">{detail.evidence_count}</Descriptions.Item>
                  <Descriptions.Item label="Provider">{detail.provider_count}</Descriptions.Item>
                  <Descriptions.Item label="关联 Proposal">
                    {detail.proposal_count}
                  </Descriptions.Item>
                  <Descriptions.Item label="过期时间">
                    {new Date(detail.expires_at).toLocaleString()}
                  </Descriptions.Item>
                </Descriptions>
                <ProviderSummary
                  detail={detail}
                  onType={(type) => state.navigate({ panel: 'evidence', providerType: type })}
                />
              </>
            ),
          },
          {
            key: 'conflicts',
            label: '完整性与冲突',
            children: (
              <Flex vertical gap={16}>
                <Completeness detail={detail} />
                <Conflicts
                  detail={detail}
                  onSelect={(index) =>
                    state.navigate({
                      panel: 'evidence',
                      conflict: String(index),
                      evidence: null,
                      sourceEvidence: null,
                      providerType: null,
                      certainty: null,
                      warnings: null,
                    })
                  }
                />
              </Flex>
            ),
          },
          { key: 'evidence', label: '证据', children: <ContextEvidenceBrowser {...props} /> },
          { key: 'knowledge', label: '知识关系', children: <ContextKnowledgePanel {...props} /> },
          {
            key: 'proposals',
            label: '关联提案',
            children: <Proposals items={detail.proposals} projectId={state.projectId} />,
          },
        ]}
      />
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

function Conflicts({
  detail,
  onSelect,
}: {
  detail: ContextDetail
  onSelect: (index: number) => void
}) {
  const conflicts = detail.revision.conflict_snapshot.conflicts
  return (
    <Card size="small" title={`Evidence Conflict · ${conflicts.length}`}>
      {conflicts.length === 0 ? (
        <Typography.Text type="secondary">当前 Revision 无冲突。</Typography.Text>
      ) : (
        conflicts.map((item, index) => (
          <Card size="small" key={`${index}:${item.subject_ref}`}>
            <Typography.Paragraph strong>{item.summary}</Typography.Paragraph>
            <Typography.Paragraph style={{ overflowWrap: 'anywhere' }} copyable>
              {item.subject_ref}
            </Typography.Paragraph>
            <Typography.Paragraph>
              固定来源引用 {item.finding_fingerprints.length} 条
            </Typography.Paragraph>
            <Button aria-label={`定位冲突证据 ${index + 1}`} onClick={() => onSelect(index)}>
              定位冲突证据
            </Button>
          </Card>
        ))
      )}
    </Card>
  )
}

function ProviderSummary({
  detail,
  onType,
}: {
  detail: ContextDetail
  onType: (
    type: import('../features/context-inspector/context-inspector-service').EvidenceProviderType,
  ) => void
}) {
  return (
    <Card size="small" title="Provider Summary">
      <Table
        size="small"
        pagination={false}
        rowKey={(item) => `${item.source_type}:${item.provider_name}:${item.provider_version}`}
        dataSource={detail.providers}
        scroll={{ x: 580 }}
        columns={[
          {
            title: 'Provider',
            render: (_, item) => `${item.provider_name} ${item.provider_version}`,
          },
          { title: '类型', dataIndex: 'source_type', render: providerLabel },
          { title: 'Finding', dataIndex: 'finding_count' },
          { title: '确定性', dataIndex: 'deterministic_count' },
          { title: '冲突', dataIndex: 'conflict_count' },
          {
            title: '定位',
            render: (_, item) => (
              <Button type="link" onClick={() => onType(item.source_type)}>
                筛选此来源类型
              </Button>
            ),
          },
        ]}
      />
    </Card>
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
          scroll={{ x: 520 }}
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

function proposalReviewLabel(value: ContextProposal['review_status']) {
  const label = value === 'accepted' ? '已接受' : value === 'rejected' ? '已拒绝' : '待审核'
  const color = value === 'accepted' ? 'success' : value === 'rejected' ? 'default' : 'warning'
  return <Tag color={color}>{label}</Tag>
}
