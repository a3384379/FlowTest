import { Empty, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import {
  definitionAssertionProvenance,
  locateAssertionSource,
  type AssertionProvenance,
  type AssertionSourceContext,
  type AssertionSourceReference,
} from './assertion-source'

export type AssertionEvidenceItem = {
  name: string
  passed: boolean | null
  expected: unknown
  actual: unknown
  message?: string
  provenance?: AssertionProvenance
}

export default function AssertionEvidence({
  items,
  source,
  location,
}: {
  items: AssertionEvidenceItem[]
  source?: string
  location?: AssertionSourceContext
}) {
  if (!items.length)
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未提供断言证据" />
  const ordered = [...items].sort(
    (left, right) => Number(left.passed !== false) - Number(right.passed !== false),
  )
  return (
    <div aria-label="断言证据">
      {ordered.map((item, index) => (
        <article
          key={`${item.name}:${index}`}
          className={`assertion-evidence${item.passed === false ? ' is-failed' : ''}`}
        >
          <header>
            <Typography.Text strong>{item.name}</Typography.Text>
            <Tag
              color={item.passed === true ? 'success' : item.passed === false ? 'error' : 'default'}
            >
              {item.passed === true ? '通过' : item.passed === false ? '失败' : '未提供结果'}
            </Tag>
          </header>
          <div className="assertion-comparison">
            <div>
              <span>期望值</span>
              <pre>{displayValue(item.expected)}</pre>
            </div>
            <div>
              <span>实际值</span>
              <pre>{displayValue(item.actual)}</pre>
            </div>
          </div>
          <NumericAssertionDifference expected={item.expected} actual={item.actual} />
          <Typography.Text type="secondary">证据来源：{source ?? '未提供'}</Typography.Text>
          {location && (
            <AssertionProvenanceView item={item} context={location} single={items.length === 1} />
          )}
          {item.message && <p>{item.message}</p>}
        </article>
      ))}
    </div>
  )
}

function AssertionProvenanceView({
  item,
  context,
  single,
}: {
  item: AssertionEvidenceItem
  context: AssertionSourceContext
  single: boolean
}) {
  const provenance = item.provenance ?? definitionAssertionProvenance(context, single)
  if (!provenance)
    return (
      <Typography.Paragraph type="secondary">
        来源定位：未解析（本次证据未提供冻结来源字段）
      </Typography.Paragraph>
    )
  return (
    <div className="assertion-provenance" aria-label="冻结断言来源">
      <Typography.Text type="secondary">
        冻结执行：{context.executionId}
        {context.instanceId ? ` · 实例：${context.instanceId}` : ''}
      </Typography.Text>
      <AssertionSourceView label="实际值来源" reference={provenance.actual} context={context} />
      {provenance.expected ? (
        <AssertionSourceView label="期望值来源" reference={provenance.expected} context={context} />
      ) : provenance.expectedKind === 'recorded' ? (
        <Typography.Paragraph>期望值来源：本次断言记录（原始来源未提供）</Typography.Paragraph>
      ) : provenance.expectedKind === 'literal' ? (
        <Typography.Paragraph>期望值来源：当次断言记录的固定值</Typography.Paragraph>
      ) : (
        <Typography.Paragraph>期望值来源：未解析（冻结来源字段不完整）</Typography.Paragraph>
      )}
      <Typography.Paragraph>
        原始表达：<code>{provenance.actual.expression ?? '未提供'}</code> · 运算符：
        {provenance.operator ?? '未提供'}
      </Typography.Paragraph>
    </div>
  )
}
function AssertionSourceView({
  label,
  reference,
  context,
}: {
  label: string
  reference: AssertionSourceReference
  context: AssertionSourceContext
}) {
  const source = locateAssertionSource(reference, context)
  return (
    <Typography.Paragraph>
      {label}：
      {source.href ? (
        <Link to={source.href}>
          {source.name}（{source.nodeId}）{source.attempt ? ` · 尝试 ${source.attempt}` : ''}
        </Link>
      ) : (
        <span>
          {source.name ?? source.nodeId} · 未解析：{source.reason}
        </span>
      )}
      <br />
      提取路径（原文）：<code>{source.expression ?? '未提供（原始断言 target 未记录）'}</code>
    </Typography.Paragraph>
  )
}

function NumericAssertionDifference({ expected, actual }: { expected: unknown; actual: unknown }) {
  if (
    typeof expected !== 'number' ||
    typeof actual !== 'number' ||
    !Number.isFinite(expected) ||
    !Number.isFinite(actual)
  )
    return null
  const delta = actual - expected
  if (!Number.isFinite(delta))
    return <Typography.Paragraph>差值超出数值范围，请查看原始期望值和实际值。</Typography.Paragraph>
  const formatted = new Intl.NumberFormat('zh-CN', {
    maximumSignificantDigits: 15,
    signDisplay: 'exceptZero',
  }).format(delta)
  return (
    <Typography.Paragraph>差值（实际 − 期望）：{formatted} · 单位：未提供</Typography.Paragraph>
  )
}

function displayValue(value: unknown): string {
  if (value === undefined) return '未提供'
  return JSON.stringify(value, null, 2) ?? '未提供'
}
