import {
  Alert,
  Badge,
  Button,
  Card,
  Descriptions,
  Empty,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ReactNode } from 'react'
import ResponseCodeReader from '../api-console/ResponseCodeReader'
import { QualityAssetEvidence } from '../quality/QualityEvidence'
import type { ImpactChange, ImpactRunDetail, SelectedAsset } from './impact-service'

type Edge = ImpactRunDetail['graph']['edges'][number]
type GraphAsset = {
  id: string
  label: string
  resolved: boolean
  edges: Edge[]
  selected?: SelectedAsset
}
type Props = {
  projectId: string
  detail: ImpactRunDetail
  changeKey: string | null
  assetKey: string | null
  onChange: (key: string | null) => void
  onAsset: (key: string | null) => void
}

export default function ImpactEvidenceWorkspace(props: Props) {
  const { detail, changeKey, onChange } = props
  const change = detail.changes.find((item) => item.key === changeKey)
  const relations = graphAssets(detail, changeKey)
  const selected = detail.selection.selected_assets.filter(
    (asset) => !changeKey || asset.change_keys.includes(changeKey),
  )
  return (
    <>
      <Card
        className="performance-card impact-evidence-metadata"
        title={`${detail.title} · ${detail.source_ref || '未指定来源引用'}`}
        extra={<Tag color="success">证据已保存</Tag>}
      >
        <Descriptions
          size="small"
          column={{ xs: 1, md: 2 }}
          items={[
            { label: '分析 ID', children: detail.id },
            { label: '冻结于', children: detail.created_at },
            { label: '来源指纹', children: detail.source_fingerprint },
          ]}
        />
        <Typography.Paragraph type="secondary">
          以下关系、测试选择和覆盖均来自本次冻结分析；项目显式映射目录表示当前配置。
        </Typography.Paragraph>
        <ChangeSelection changeKey={changeKey} change={change} onChange={onChange} />
        <div className="impact-workspace">
          <ImpactColumn title="① 变更" count={detail.changes.length}>
            {detail.changes.map((item) => (
              <ChangeItem
                key={item.key}
                change={item}
                selected={item.key === changeKey}
                onSelect={() => onChange(item.key)}
              />
            ))}
          </ImpactColumn>
          <ImpactColumn
            title="② 受影响资产"
            count={relations.filter((asset) => asset.resolved).length}
          >
            <Typography.Text type="secondary">
              关联关系 {relations.reduce((total, asset) => total + asset.edges.length, 0)} 条
            </Typography.Text>
            {relations.map((asset) => (
              <GraphAssetItem
                key={asset.id}
                asset={asset}
                detail={detail}
                onSelect={() => props.onAsset(asset.id)}
              />
            ))}
            {!relations.length && (
              <Empty description={changeKey ? '当前变更未命中资产' : '暂无命中资产'} />
            )}
          </ImpactColumn>
          <ImpactColumn title="③ 推荐测试集" count={selected.length}>
            <Typography.Text type="secondary">策略：{detail.selection.strategy}</Typography.Text>
            {selected.map((asset) => (
              <article className="impact-item" key={assetKey(asset)}>
                <Typography.Text strong>{asset.name}</Typography.Text>
                <Typography.Text>
                  固定版本：{asset.version ?? '未提供'} · 覆盖 {asset.change_keys.length} 个变更
                </Typography.Text>
                {asset.reasons.map((reason) => (
                  <Typography.Text type="secondary" key={reason}>
                    {reason}
                  </Typography.Text>
                ))}
                <Tag>{asset.target_type}</Tag>
                <Button onClick={() => props.onAsset(assetKey(asset))}>
                  查看推荐 {asset.name}
                </Button>
              </article>
            ))}
            {!selected.length && (
              <Empty description={changeKey ? '当前变更没有推荐测试' : '需要补充显式映射'} />
            )}
          </ImpactColumn>
        </div>
        {change && <ChangeEvidence change={change} />}
      </Card>
      {props.assetKey && <AssetEvidence {...props} />}
      <CoverageMatrix {...props} />
    </>
  )
}

function ChangeSelection({
  changeKey,
  change,
  onChange,
}: {
  changeKey: string | null
  change?: ImpactChange
  onChange: (key: string | null) => void
}) {
  if (!changeKey) return null
  return (
    <>
      <Space wrap className="page-alert">
        <Typography.Text>当前变更：{change?.label ?? changeKey}</Typography.Text>
        <Button onClick={() => onChange(null)}>显示全部变更</Button>
      </Space>
      {!change && (
        <Alert type="error" title="指定变更未出现在当前冻结分析中" description={changeKey} />
      )}
    </>
  )
}

function ImpactColumn({
  title,
  count,
  children,
}: {
  title: string
  count: number
  children: ReactNode
}) {
  return (
    <section aria-label={title} className="impact-column">
      <div className="impact-column-title">
        <Typography.Text strong>{title}</Typography.Text>
        <Badge count={count} showZero />
      </div>
      <div className="impact-column-body">{children}</div>
    </section>
  )
}

function ChangeItem({
  change,
  selected,
  onSelect,
}: {
  change: ImpactChange
  selected: boolean
  onSelect: () => void
}) {
  return (
    <article
      className={`impact-item impact-item-${change.severity}${selected ? ' impact-item-selected' : ''}`}
    >
      <Space wrap>
        <Tag color={change.severity === 'breaking' ? 'error' : 'blue'}>{change.severity}</Tag>
        <Tag>{change.source_kind}</Tag>
      </Space>
      <Button
        type="link"
        className="impact-evidence-select"
        aria-label={`选择变更 ${change.label}`}
        aria-pressed={selected}
        onClick={onSelect}
      >
        {change.label}
      </Button>
      <Typography.Text type="secondary">{change.detail}</Typography.Text>
    </article>
  )
}

function graphAssets(detail: ImpactRunDetail, changeKey: string | null): GraphAsset[] {
  const grouped = new Map<string, GraphAsset>()
  const edges = detail.graph.edges.filter(
    (edge) => !changeKey || edge.from === `change:${changeKey}`,
  )
  for (const edge of edges) {
    const existing = grouped.get(edge.to)
    if (existing) {
      existing.edges.push(edge)
      continue
    }
    const node = detail.graph.nodes.find((item) => item.id === edge.to && item.kind === 'asset')
    grouped.set(edge.to, {
      id: edge.to,
      label: node?.label ?? edge.to,
      resolved: Boolean(node),
      edges: [edge],
      selected: detail.selection.selected_assets.find((asset) => assetKey(asset) === edge.to),
    })
  }
  return [...grouped.values()]
}

function GraphAssetItem({
  asset,
  detail,
  onSelect,
}: {
  asset: GraphAsset
  detail: ImpactRunDetail
  onSelect: () => void
}) {
  return (
    <article className="impact-item">
      <Typography.Text strong>{asset.label}</Typography.Text>
      <Typography.Text type="secondary">{asset.id}</Typography.Text>
      {asset.edges.map((edge, index) => (
        <Typography.Text key={`${edge.from}:${index}`}>
          {detail.changes.find((change) => `change:${change.key}` === edge.from)?.label ??
            edge.from}{' '}
          → {edge.reason}
        </Typography.Text>
      ))}
      {!asset.resolved && (
        <Typography.Text type="warning">原始关系引用，未提供可确认的资产节点</Typography.Text>
      )}
      <Button onClick={onSelect}>
        {asset.resolved ? '查看资产' : '查看原始引用'} {asset.label}
      </Button>
    </article>
  )
}

function assetKey(asset: SelectedAsset): string {
  return `asset:${asset.target_type}:${asset.target_id}`
}

function ChangeEvidence({ change }: { change: ImpactChange }) {
  return (
    <Card size="small" title="变更前后证据" className="impact-gap-alert">
      <Typography.Paragraph>
        {change.source_kind} · {change.source_key} · {change.change_type}
      </Typography.Paragraph>
      <ResponseCodeReader value={change.before} title="变更前" />
      <ResponseCodeReader value={change.after} title="变更后" />
    </Card>
  )
}

function AssetEvidence(props: Props) {
  const asset = props.detail.selection.selected_assets.find(
    (item) => assetKey(item) === props.assetKey,
  )
  const graph = graphAssets(props.detail, null).find((item) => item.id === props.assetKey)
  const issue = assetEvidenceIssue(asset, graph, props.changeKey)
  return (
    <Card
      title="选中资产与固定证据"
      className="performance-card impact-evidence-metadata"
      extra={<Button onClick={() => props.onAsset(null)}>关闭资产详情</Button>}
    >
      <Typography.Paragraph>{props.assetKey}</Typography.Paragraph>
      {asset && !issue ? (
        <>
          <Typography.Title level={4}>{asset.name}</Typography.Title>
          <Descriptions
            column={1}
            items={[
              { label: '完整资产', children: `${asset.target_type}:${asset.target_id}` },
              { label: '固定版本', children: asset.version ?? '未提供' },
              { label: '风险', children: asset.risk },
            ]}
          />
          {asset.reasons.map((reason) => (
            <Typography.Paragraph key={reason}>{reason}</Typography.Paragraph>
          ))}
          <QualityAssetEvidence
            key={`${props.detail.id}:${props.assetKey}`}
            projectId={props.projectId}
            type={asset.target_type}
            id={asset.target_id}
            version={asset.version}
          />
          <Space wrap>
            {asset.change_keys.map((key) => (
              <Button key={key} onClick={() => props.onChange(key)}>
                定位来源变更 {props.detail.changes.find((item) => item.key === key)?.label ?? key}
              </Button>
            ))}
          </Space>
        </>
      ) : (
        <Alert
          type="info"
          title={issue ?? '未提供可读取的固定资产版本'}
          description={graph?.label ?? props.assetKey}
        />
      )}
      {graph?.edges.map((edge, index) => (
        <Typography.Paragraph key={`${edge.from}:${index}`}>
          {edge.from} → {edge.to} · {edge.reason}
        </Typography.Paragraph>
      ))}
    </Card>
  )
}

function assetEvidenceIssue(
  asset: SelectedAsset | undefined,
  graph: GraphAsset | undefined,
  changeKey: string | null,
): string | null {
  if (asset)
    return changeKey && !asset.change_keys.includes(changeKey)
      ? '选中资产与当前变更没有冻结关联'
      : null
  return graph ? '该关系未提供可读取的固定资产版本，保留原始引用' : '指定资产未出现在当前冻结分析中'
}

function CoverageMatrix(props: Props) {
  const { coverage, selection } = props.detail
  const rows = coverage.matrix.filter(
    (row) => !props.changeKey || row.change_key === props.changeKey,
  )
  const gaps = coverage.gaps.filter((gap) => !props.changeKey || gap.change_key === props.changeKey)
  return (
    <Card title="Test Mapping / Coverage Matrix" className="performance-card">
      <Typography.Paragraph type="secondary">
        整份冻结分析覆盖率 {coverage.coverage_percent}% · {coverage.covered_changes}/
        {coverage.total_changes} 项变更；当前定位 {rows.length} 项。
      </Typography.Paragraph>
      <Table
        rowKey="change_key"
        size="small"
        pagination={false}
        dataSource={rows}
        scroll={{ x: 720 }}
        locale={{ emptyText: '当前定位没有覆盖记录' }}
        columns={[
          {
            title: '变更',
            key: 'change',
            render: (_, row) => (
              <Button
                type="link"
                className="impact-evidence-select"
                aria-label={`定位覆盖变更 ${row.label}`}
                onClick={() => props.onChange(row.change_key)}
              >
                {row.label}
              </Button>
            ),
          },
          { title: '来源', dataIndex: 'source_kind' },
          ...(['case', 'workflow', 'contract', 'performance'] as const).map((type) => ({
            title: {
              case: 'Case',
              workflow: 'Workflow',
              contract: 'Contract',
              performance: '性能',
            }[type],
            key: type,
            render: (_: unknown, row: ImpactRunDetail['coverage']['matrix'][number]) => (
              <Space orientation="vertical">
                <Typography.Text>{row[`${type}_count`]}</Typography.Text>
                {selection.selected_assets
                  .filter(
                    (asset) =>
                      asset.asset_type === type && asset.change_keys.includes(row.change_key),
                  )
                  .map((asset) => (
                    <Button
                      type="link"
                      key={assetKey(asset)}
                      onClick={() => props.onAsset(assetKey(asset))}
                    >
                      查看覆盖资产 {asset.name}
                    </Button>
                  ))}
              </Space>
            ),
          })),
          {
            title: '覆盖',
            dataIndex: 'covered',
            render: (value: boolean) => (
              <Tag color={value ? 'success' : 'error'}>{value ? '已覆盖' : '缺口'}</Tag>
            ),
          },
        ]}
      />
      {gaps.length > 0 && (
        <Alert
          className="impact-gap-alert"
          type="warning"
          showIcon
          title={`${gaps.length} 个覆盖缺口`}
          description={gaps.map((gap) => `${gap.source_key}：${gap.reason}`).join('；')}
        />
      )}
    </Card>
  )
}
