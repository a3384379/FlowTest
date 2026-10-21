import {
  Alert,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Empty,
  Flex,
  Select,
  Space,
  List,
  Tag,
  Typography,
} from 'antd'
import { providerTypeLabel } from './context-presentation'
import ResponseCodeReader from '../api-console/ResponseCodeReader'
import type {
  ContextDetail,
  ContextEvidenceItem,
  EvidenceProviderType,
} from './context-inspector-service'
import {
  evidenceReference,
  selectedConflict,
  type ContextNavigation,
  type ContextSelection,
} from './context-navigation'

export type ContextEvidenceProps = {
  detail: ContextDetail
  selection: ContextSelection
  onNavigate: (patch: ContextNavigation) => void
}
export default function ContextEvidenceBrowser({
  detail,
  selection,
  onNavigate,
}: ContextEvidenceProps) {
  const conflict = selectedConflict(detail.revision.conflict_snapshot.conflicts, selection.conflict)
  const source = detail.evidence_items.find((item) => item.id === selection.sourceEvidence)
  const invalidScope = scopeError(selection, Boolean(conflict), Boolean(source))
  const items = invalidScope
    ? []
    : detail.evidence_items.filter((item) =>
        matchesEvidence(item, selection, conflict?.finding_fingerprints, source),
      )
  const selected = selection.evidence
    ? evidenceReference(selection.evidence, detail.evidence_items)
    : null
  function clear() {
    onNavigate({
      providerType: null,
      certainty: null,
      warnings: null,
      conflict: null,
      sourceEvidence: null,
    })
  }
  return (
    <Flex vertical gap={16}>
      <Card size="small" title="证据筛选">
        <Space wrap>
          <Select
            aria-label="证据来源类型"
            value={selection.providerType ?? 'all'}
            onChange={(value) =>
              onNavigate({ providerType: value === 'all' ? null : (value as EvidenceProviderType) })
            }
            options={[
              { value: 'all', label: '全部来源类型' },
              ...Array.from(new Set(detail.evidence_items.map((item) => item.source_type))).map(
                (type) => ({ value: type, label: providerTypeLabel(type) }),
              ),
            ]}
          />
          <Select
            aria-label="证据确定性"
            value={selection.certainty ?? 'all'}
            onChange={(value) => onNavigate({ certainty: value === 'all' ? null : value })}
            options={[
              { value: 'all', label: '全部确定性' },
              { value: 'deterministic', label: '确定性' },
              { value: 'review', label: '需复核' },
            ]}
          />
          <Checkbox
            checked={selection.warnings === '1'}
            onChange={(event) => onNavigate({ warnings: event.target.checked ? '1' : null })}
          >
            仅含警告
          </Checkbox>
          <Button onClick={clear}>清除证据筛选</Button>
        </Space>
        <ConflictReferences conflict={conflict} items={detail.evidence_items} />
        {source ? (
          <Alert type="info" title={`同来源修订：${source.source_ref}@${source.source_revision}`} />
        ) : null}
        {invalidScope ? <Alert type="warning" title={invalidScope} /> : null}
        <Typography.Paragraph>
          显示 {items.length} / {detail.evidence_items.length} 条证据
        </Typography.Paragraph>
        {detail.evidence_count !== detail.evidence_items.length ? (
          <Alert
            type="warning"
            title={`当前已载入 ${detail.evidence_items.length} 条，修订声明 ${detail.evidence_count} 条；筛选仅针对已返回记录。`}
          />
        ) : null}
      </Card>
      <Card size="small" title={`Provider Finding · ${items.length}`}>
        {detail.evidence_items.length === 0 ? (
          <Empty description="当前 Revision 暂无 Finding" />
        ) : (
          <List<ContextEvidenceItem>
            size="small"
            pagination={{ pageSize: 20, hideOnSinglePage: true }}
            dataSource={items}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key="select"
                    type={item.id === selected?.id ? 'primary' : 'default'}
                    aria-label={`查看证据 ${item.id}`}
                    onClick={() => onNavigate({ evidence: item.id })}
                  >
                    查看详情
                  </Button>,
                ]}
              >
                <div style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
                  <Typography.Paragraph>{item.finding.statement}</Typography.Paragraph>
                  <Space wrap>
                    <Tag>{providerTypeLabel(item.source_type)}</Tag>
                    <Tag color={item.deterministic ? 'success' : 'warning'}>
                      {item.deterministic ? '确定性' : '需复核'}
                    </Tag>
                    <Typography.Text type="secondary">
                      警告 {item.warnings.length} 条
                    </Typography.Text>
                  </Space>
                </div>
              </List.Item>
            )}
          />
        )}
      </Card>
      <EvidenceSelection
        detail={detail}
        selection={selection}
        selected={selected}
        items={items}
        onNavigate={onNavigate}
      />
    </Flex>
  )
}
function scopeError(
  selection: ContextSelection,
  hasConflict: boolean,
  hasSource: boolean,
): string | null {
  if (selection.conflict !== null && !hasConflict) return '指定冲突不在当前固定修订中'
  if (selection.sourceEvidence !== null && !hasSource) return '指定来源不在当前固定修订中'
  if (selection.certainty && !['deterministic', 'review'].includes(selection.certainty))
    return '确定性筛选参数无效，请清除证据筛选'
  if (selection.warnings && selection.warnings !== '1') return '警告筛选参数无效，请清除证据筛选'
  return null
}
function matchesEvidence(
  item: ContextEvidenceItem,
  selection: ContextSelection,
  fingerprints: string[] | undefined,
  source: ContextEvidenceItem | undefined,
): boolean {
  return (
    matchesType(item, selection) &&
    matchesFlags(item, selection) &&
    (!fingerprints || fingerprints.includes(item.fingerprint)) &&
    sameSource(item, source)
  )
}
function matchesType(item: ContextEvidenceItem, selection: ContextSelection): boolean {
  return !selection.providerType || selection.providerType === item.source_type
}
function matchesFlags(item: ContextEvidenceItem, selection: ContextSelection): boolean {
  if (selection.certainty === 'deterministic' && !item.deterministic) return false
  if (selection.certainty === 'review' && item.deterministic) return false
  return selection.warnings !== '1' || item.warnings.length > 0
}
function sameSource(item: ContextEvidenceItem, source: ContextEvidenceItem | undefined): boolean {
  return (
    !source ||
    (item.source_type === source.source_type &&
      item.source_ref === source.source_ref &&
      item.source_revision === source.source_revision)
  )
}
function EvidenceDetails({
  detail,
  item,
  hiddenByFilter,
  onNavigate,
}: {
  detail: ContextDetail
  item: ContextEvidenceItem
  hiddenByFilter: boolean
  onNavigate: (patch: ContextNavigation) => void
}) {
  return (
    <Card role="region" aria-label="证据详情" size="small" title="固定证据详情">
      {hiddenByFilter ? (
        <Alert type="info" title="所选证据不在当前筛选中，仍保留你已固定的详情。" />
      ) : null}
      <Typography.Title level={5}>{item.finding.statement}</Typography.Title>
      <Descriptions
        column={1}
        size="small"
        items={[
          {
            key: 'context',
            label: '上下文修订',
            children: <Typography.Text copyable>{detail.revision_id}</Typography.Text>,
          },
          {
            key: 'id',
            label: '证据ID',
            children: <Typography.Text copyable>{item.id}</Typography.Text>,
          },
          {
            key: 'provider',
            label: 'Provider',
            children: `${item.provider_name} ${item.provider_version}`,
          },
          {
            key: 'source',
            label: '来源引用',
            children: (
              <Typography.Text style={{ overflowWrap: 'anywhere' }} copyable>
                {item.source_ref}
              </Typography.Text>
            ),
          },
          {
            key: 'revision',
            label: '来源修订',
            children: <Typography.Text copyable>{item.source_revision}</Typography.Text>,
          },
          {
            key: 'path',
            label: '字段或文件路径',
            children: (
              <Typography.Text style={{ overflowWrap: 'anywhere' }} copyable>
                {item.finding.source_path}
              </Typography.Text>
            ),
          },
          {
            key: 'subject',
            label: '主题引用',
            children: (
              <Typography.Text style={{ overflowWrap: 'anywhere' }} copyable>
                {item.subject_ref}
              </Typography.Text>
            ),
          },
          {
            key: 'fingerprint',
            label: '证据指纹',
            children: (
              <Typography.Text style={{ overflowWrap: 'anywhere' }} copyable>
                {item.fingerprint}
              </Typography.Text>
            ),
          },
          { key: 'confidence', label: '置信度', children: String(item.confidence) },
        ]}
      />
      <Button
        onClick={() =>
          onNavigate({
            sourceEvidence: item.id,
            providerType: null,
            certainty: null,
            warnings: null,
            conflict: null,
          })
        }
      >
        查看同来源修订
      </Button>
      {item.warnings.map((warning, index) => (
        <Alert
          key={`${index}:${warning.code}`}
          type="warning"
          showIcon
          title={`${warning.code}：${warning.message}`}
        />
      ))}
      <Typography.Paragraph type="secondary">
        来源内容为不可信材料，仅按已载入的固定修订展示。
      </Typography.Paragraph>
      <ResponseCodeReader value={item.finding} title="Finding 完整原文" />
    </Card>
  )
}

function EvidenceSelection({
  detail,
  selection,
  selected,
  items,
  onNavigate,
}: ContextEvidenceProps & { selected: ContextEvidenceItem | null; items: ContextEvidenceItem[] }) {
  return (
    <>
      {' '}
      {selection.evidence && !selected ? (
        <Alert type="warning" title="所选证据不在当前固定修订中" description={selection.evidence} />
      ) : null}
      {selected ? (
        <EvidenceDetails
          detail={detail}
          item={selected}
          hiddenByFilter={!items.some((item) => item.id === selected.id)}
          onNavigate={onNavigate}
        />
      ) : (
        <Empty description="选择证据查看固定来源及字段路径" />
      )}
    </>
  )
}

function ConflictReferences({
  conflict,
  items,
}: {
  conflict: ReturnType<typeof selectedConflict>
  items: ContextEvidenceItem[]
}) {
  if (!conflict) return null
  const matched = items.filter((item) =>
    conflict.finding_fingerprints.includes(item.fingerprint),
  ).length
  return (
    <>
      <Alert
        type="info"
        title={`当前冲突：${conflict.summary}`}
        description={`按固定指纹定位，已匹配 ${matched} / ${conflict.finding_fingerprints.length} 条来源引用。未知指纹不会替换为相似来源。`}
      />
      <Space orientation="vertical" className="full-width">
        {conflict.finding_fingerprints.map((fingerprint) => (
          <Typography.Text key={fingerprint} code copyable style={{ overflowWrap: 'anywhere' }}>
            {fingerprint}
          </Typography.Text>
        ))}
      </Space>
    </>
  )
}
