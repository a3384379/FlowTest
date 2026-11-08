import { useSelfTestInsights } from './use-self-test-insights'
import SelfTestAssistedEditor from './SelfTestAssistedEditor'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { Alert, Button, Card, Collapse, Table, Typography } from 'antd'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import type { SelfTestBatch } from './self-test-contract'
import { useSelfTestIdentity } from './self-test-query-keys'

export default function SelfTestInsights({
  projectId,
  batch,
}: {
  projectId: string
  batch: SelfTestBatch
}) {
  const identity = useSelfTestIdentity(projectId)
  const query = useSelfTestInsights(projectId, batch)
  const permissions = useProjectCapabilities()
  return (
    <Card
      title="冻结范围指标与生成诊断"
      extra={
        <Button loading={query.isFetching} onClick={() => void query.refetch()}>
          刷新统计与诊断
        </Button>
      }
    >
      <QueryFailureNotice queries={[query]} />
      {query.isSuccess && query.data?.assisted_before_batch_id && (
        <SelfTestAssistedEditor
          key={`${identity.userId}:${identity.organizationId}:${identity.epoch}:${projectId}:${batch.id}`}
          projectId={projectId}
          batchId={batch.id}
          beforeBatchId={query.data.assisted_before_batch_id}
          allowed={
            permissions.canEdit &&
            !batch.sealed_at &&
            ['pending', 'generating', 'awaiting_review'].includes(batch.phase)
          }
        />
      )}
      {query.isSuccess && query.data && (
        <>
          <Typography.Paragraph>
            范围：{query.data.scope} · 模板 v{query.data.template_version} · 任务集{' '}
            {query.data.task_set_digest}
          </Typography.Paragraph>
          <Table
            size="small"
            pagination={false}
            rowKey="key"
            dataSource={query.data.metrics}
            scroll={{ x: 750 }}
            columns={[
              { title: '指标', dataIndex: 'label' },
              {
                title: '分子 / 分母',
                render: (_, row) =>
                  `${row.numerator} / ${row.denominator} · ${row.denominator ? `${((row.numerator / row.denominator) * 100).toFixed(1)}%` : '未评估'}`,
              },
              { title: '统计口径', dataIndex: 'basis' },
              { title: '排除原因', render: (_, row) => row.exclusions.join(' · ') || '无' },
            ]}
          />
          <Collapse
            items={[
              {
                key: 'diagnostics',
                label: `编译诊断与待补输入（${query.data.diagnostics.length}）`,
                children: (
                  <Table
                    size="small"
                    pagination={{ pageSize: 10 }}
                    rowKey={(_, index) => String(index)}
                    dataSource={query.data.diagnostics}
                    scroll={{ x: 850 }}
                    locale={{ emptyText: '当前已记录回执没有诊断；未完成编译不代表编译通过。' }}
                    columns={[
                      { title: '严重度', dataIndex: 'severity' },
                      { title: '原因码', dataIndex: 'code' },
                      {
                        title: '场景 / Oracle',
                        render: (_, row) =>
                          `${row.scenario_id ?? '批次'} / ${row.oracle_id ?? '—'}`,
                      },
                      { title: '字段位置', dataIndex: 'field_path' },
                      { title: '下一步', dataIndex: 'repair_hint' },
                    ]}
                  />
                ),
              },
              {
                key: 'slots',
                label: `Case 模板与流程槽位（${query.data.case_slots.length}）`,
                children: (
                  <Table
                    size="small"
                    pagination={{ pageSize: 10 }}
                    rowKey={(row) => `${row.scenario_id}:${row.variant_key}`}
                    dataSource={query.data.case_slots}
                    columns={[
                      { title: '场景', dataIndex: 'scenario_id' },
                      {
                        title: '流程槽位',
                        render: (_, row) => row.workflow_slot ?? '编译槽位尚未记录',
                      },
                      {
                        title: '固定 Case',
                        render: (_, row) => `${row.case_id}@${row.case_version}`,
                      },
                      { title: '环境', dataIndex: 'environment_id' },
                    ]}
                  />
                ),
              },
            ]}
          />
          {!!query.data.reason_codes.length && (
            <Alert
              type="info"
              title="部分观察证据尚未形成，未提供的指标或对照保持未评估"
              description={query.data.reason_codes.join(' · ')}
            />
          )}
        </>
      )}
    </Card>
  )
}
