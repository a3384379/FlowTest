import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Modal,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import CatalogPagination from '../../components/CatalogPagination'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import ResponseCodeReader from '../api-console/ResponseCodeReader'
import { qualityRunPath } from './quality-navigation'
import { listWorkflowVersions } from '../workflows/workflow-service'
import { listTestCaseVersions, listTestSuiteVersions } from '../test-assets/test-asset-service'
import type { useQualityCenter } from './use-quality-center'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { projectPath } from '../projects/project-routing'
import ContractEvidenceViewer from '../contracts/ContractEvidenceDrawer'

type QualityState = ReturnType<typeof useQualityCenter>

export function QualityRiskHistory({ state }: { state: QualityState }) {
  const [expanded, setExpanded] = useRouteScopedState(state.projectId, null, false)
  if (!state.riskEnabled) return null
  return (
    <Card
      title="风险快照历史"
      className="quality-runs-card"
      extra={
        <Button aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
          {expanded ? '收起历史' : '切换风险快照'}
        </Button>
      }
    >
      {!expanded ? (
        <Typography.Text type="secondary">展开选择已保存快照，翻页保持当前证据。</Typography.Text>
      ) : (
        <>
          <CatalogPagination query={state.risks} label="风险记录" />
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            scroll={{ x: 700, y: 300 }}
            loading={state.risks.isLoading}
            dataSource={state.risks.data?.items ?? []}
            locale={{ emptyText: '暂无风险快照' }}
            rowClassName={(row) =>
              row.id === state.linkedRiskId ? 'quality-selected-evidence' : ''
            }
            columns={[
              {
                title: '候选版本',
                render: (_, row) => (
                  <Button
                    type="link"
                    className="quality-risk-name"
                    aria-label={`打开风险 ${row.id}`}
                    onClick={() => state.selectEvidence('risk', row.id)}
                  >
                    {row.title}
                  </Button>
                ),
              },
              { title: '风险分', dataIndex: 'score' },
              { title: '证据窗口', render: (_, row) => `${row.window_days} 天` },
              { title: '生成时间', dataIndex: 'created_at' },
              {
                title: '选择',
                render: (_, row) =>
                  row.id === state.linkedRiskId ? (
                    <Tag color="blue">当前快照</Tag>
                  ) : (
                    <Button onClick={() => state.selectEvidence('risk', row.id)}>查看</Button>
                  ),
              },
            ]}
          />
        </>
      )}
    </Card>
  )
}

export function QualityFlakyEvidence({ state }: { state: QualityState }) {
  if (!state.linkedRecordId || !state.projectId) return null
  const record = state.record.isSuccess ? state.record.data : undefined
  return (
    <Card
      title="Flaky 固定版本证据"
      className="quality-runs-card"
      extra={<Button onClick={() => state.selectEvidence('record', null)}>关闭详情</Button>}
    >
      <QueryFailureNotice queries={[state.record]} />
      {state.record.isPending && <Typography.Text>正在读取指定 Flaky 记录</Typography.Text>}
      {record && (
        <Space orientation="vertical" className="full-width">
          <Descriptions
            bordered
            size="small"
            column={1}
            items={[
              { label: '记录 ID', children: record.id },
              {
                label: '完整资产',
                children: `${record.target_type}:${record.target_id}@${record.target_version}`,
              },
              {
                label: '累计通过 / 失败 / 总运行',
                children: `${record.passed_runs} / ${record.failed_runs} / ${record.total_runs}`,
              },
              { label: 'Flaky 得分', children: record.flaky_score },
              {
                label: '隔离状态',
                children: (
                  <Space wrap>
                    <Typography.Text>{record.quarantined ? '已隔离' : '未隔离'}</Typography.Text>
                    <Switch
                      aria-label={`隔离选中记录 ${record.id}`}
                      checked={record.quarantined}
                      loading={state.toggling}
                      disabled={!state.canEdit}
                      onChange={(value) => void state.toggleQuarantine(record.id, value)}
                    />
                  </Space>
                ),
              },
              { label: '最后更新', children: record.updated_at },
            ]}
          />
          {record.last_run_id && (
            <Link to={qualityRunPath(state.projectId, record.last_run_id)}>
              打开最后一次计划运行
            </Link>
          )}
          <QualityTargetVersion
            projectId={state.projectId}
            type={record.target_type}
            id={record.target_id}
            version={record.target_version}
          />
        </Space>
      )}
    </Card>
  )
}

export function QualityTargetVersion({
  projectId,
  type,
  id,
  version,
}: {
  projectId: string
  type: string
  id: string
  version: number
}) {
  const supported = ['workflow', 'case', 'suite'].includes(type)
  const snapshot = useQuery({
    queryKey: ['quality-target-version', projectId, type, id, version],
    queryFn: () => readTargetVersion(projectId, type, id, version),
    enabled: supported,
  })
  if (!supported) return <Alert type="info" title={`暂不支持查看 ${type} 的固定版本`} />
  return (
    <Card size="small" title={`固定资产版本 v${version}`}>
      <QueryFailureNotice queries={[snapshot]} />
      {snapshot.isPending && <Typography.Text>正在读取固定资产版本</Typography.Text>}
      {snapshot.data && (
        <>
          <Typography.Paragraph>版本指纹：{snapshot.data.fingerprint}</Typography.Paragraph>
          <ResponseCodeReader value={snapshot.data.definition} title="原始固定版本配置" />
        </>
      )}
    </Card>
  )
}

async function readTargetVersion(projectId: string, type: string, id: string, version: number) {
  const found =
    type === 'workflow'
      ? (await listWorkflowVersions(projectId, id)).find(
          (item) => item.workflow_id === id && item.version === version,
        )
      : type === 'case'
        ? (await listTestCaseVersions(projectId, id)).find(
            (item) => item.test_case_id === id && item.version === version,
          )
        : (await listTestSuiteVersions(projectId, id)).find(
            (item) => item.test_suite_id === id && item.version === version,
          )
  if (!found) throw new Error('指定资产版本不存在或已不可访问，请核对原始记录；未替换为最新版本')
  return found
}

export function QualityAssetEvidence(props: {
  projectId: string
  type: string
  id: string
  version: number | string | null
}) {
  if (props.type === 'openapi_contract' || props.type === 'pact_contract')
    return (
      <QualityContractEvidence
        {...props}
        kind={props.type === 'openapi_contract' ? 'run' : 'pact'}
      />
    )
  if (props.type === 'performance')
    return (
      <Link
        to={`${projectPath(props.projectId, 'performance')}?${new URLSearchParams({ scenario: props.id })}`}
      >
        查看固定性能场景
      </Link>
    )
  return (
    <QualityTestAssetEvidence {...props} type={props.type === 'test_case' ? 'case' : props.type} />
  )
}

function QualityContractEvidence({
  projectId,
  id,
  kind,
}: {
  projectId: string
  id: string
  kind: 'run' | 'pact'
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button onClick={() => setOpen(true)}>查看固定契约</Button>
      <ContractEvidenceViewer
        projectId={projectId}
        selection={open ? { kind, id } : null}
        onClose={() => setOpen(false)}
      />
    </>
  )
}

function QualityTestAssetEvidence(props: {
  projectId: string
  type: string
  id: string
  version: number | string | null
}) {
  const [open, setOpen] = useState(false)
  const valid =
    typeof props.version === 'number' &&
    Number.isSafeInteger(props.version) &&
    props.version > 0 &&
    ['workflow', 'case', 'suite'].includes(props.type)
  if (!valid) return <Typography.Text type="secondary">未提供可读取的固定版本</Typography.Text>
  return (
    <>
      <Button onClick={() => setOpen(true)}>查看固定版本</Button>
      <Modal
        title="推荐资产固定版本"
        className="quality-snapshot-dialog"
        open={open}
        footer={null}
        width={900}
        onCancel={() => setOpen(false)}
        destroyOnHidden
      >
        {open && <QualityTargetVersion {...props} version={props.version as number} />}
      </Modal>
    </>
  )
}
