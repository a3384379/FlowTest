import { Alert, Card, Empty, Space, Table, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { PriorityIssue } from './priority-issues'

export default function PriorityIssueQueue({
  issues,
  loading,
  incomplete,
}: {
  issues: PriorityIssue[]
  loading: boolean
  incomplete: boolean
}) {
  return (
    <section aria-label="优先处理的问题" className="quality-priority-queue">
      <Card
        title="优先处理的问题"
        extra={<Typography.Text type="secondary">已读取来源中 {issues.length} 条</Typography.Text>}
      >
        <Typography.Paragraph type="secondary">
          处理顺序：发布阻断 → 冻结失败簇 → 最近失败 → 覆盖缺口 →
          Flaky。同类按发生次数、时间或来源得分排序。
        </Typography.Paragraph>
        {loading && <Alert type="info" title="部分问题来源仍在加载，已读取的问题先行显示。" />}
        {incomplete && (
          <Alert
            type="warning"
            title="部分来源读取失败，当前队列不完整，不能据此判断所有风险已消除。"
          />
        )}
        <Table<PriorityIssue>
          rowKey="id"
          size="small"
          dataSource={issues}
          pagination={{ pageSize: 8, showSizeChanger: false, hideOnSinglePage: true }}
          scroll={{ x: 650 }}
          locale={{ emptyText: <Empty description={emptyDescription(loading, incomplete)} /> }}
          columns={[
            {
              title: '优先项',
              key: 'priority',
              width: 140,
              render: (_, issue) => (
                <Tag color={issue.rank === 0 ? 'error' : 'warning'}>{issue.category}</Tag>
              ),
            },
            {
              title: '问题与数据范围',
              key: 'issue',
              render: (_, issue) => (
                <Space orientation="vertical" size={4}>
                  <Typography.Text strong>{issue.title}</Typography.Text>
                  <Typography.Text>{issue.description}</Typography.Text>
                  <Typography.Text type="secondary">{issue.scope}</Typography.Text>
                </Space>
              ),
            },
            {
              title: '证据入口',
              key: 'action',
              width: 165,
              render: (_, issue) => <Link to={issue.href}>{issue.action}</Link>,
            },
          ]}
        />
      </Card>
    </section>
  )
}

function emptyDescription(loading: boolean, incomplete: boolean): string {
  if (incomplete) return '来源尚未读取完整，暂无法确认问题队列'
  return loading ? '等待当前来源返回问题证据' : '已读取来源中暂无待处理问题'
}
