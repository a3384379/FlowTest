import { Progress, Space, Typography } from 'antd'
import type { CoverageEntry } from './test-engineering-service'

export default function DesignCoverageSummary({ entries }: { entries?: CoverageEntry[] }) {
  if (!entries) return <Typography.Text type="secondary">未评估：覆盖数据未提供</Typography.Text>
  const evaluatedCount = entries.filter((item) => typeof item.covered === 'boolean').length
  const coveredCount = entries.filter((item) => item.covered === true).length
  const percent =
    entries.length && evaluatedCount === entries.length
      ? Math.round((coveredCount * 100) / entries.length)
      : null
  return (
    <Space wrap>
      <Typography.Text>
        已覆盖 {coveredCount} / {entries.length} 项
      </Typography.Text>
      {percent === null ? (
        <Typography.Text type="secondary">
          {entries.length
            ? `未评估：${entries.length - evaluatedCount} 项缺少评估结果`
            : '无可评估项'}
        </Typography.Text>
      ) : (
        <Progress aria-label="设计覆盖率" size={46} type="circle" percent={percent} />
      )}
    </Space>
  )
}
