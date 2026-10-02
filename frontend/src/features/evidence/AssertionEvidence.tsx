import { Empty, Tag, Typography } from 'antd'

export type AssertionEvidenceItem = {
  name: string
  passed: boolean | null
  expected: unknown
  actual: unknown
  message?: string
}

export default function AssertionEvidence({ items }: { items: AssertionEvidenceItem[] }) {
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
          {item.message && <p>{item.message}</p>}
        </article>
      ))}
    </div>
  )
}

function displayValue(value: unknown): string {
  if (value === undefined) return '未提供'
  return JSON.stringify(value, null, 2) ?? '未提供'
}
