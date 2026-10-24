import { Card, Steps, Typography } from 'antd'
import type { SelfTestRelation, SelfTestSource, SelfTestScenario } from './self-test-contract'
import { scenarioHasCompleteEvidence } from './self-test-verdict'

export default function SelfTestSourceChain({ relation }: { relation: SelfTestRelation }) {
  const { batch, scenario, execution_id: executionId } = relation
  const source = scenario.source
  const asset = source ?? scenario.published_assets
  const verified = scenarioHasCompleteEvidence(batch, scenario)
  const fixed = batch.batch_kind === 'fixed_baseline'
  const items = [
    ...designSteps(relation),
    ...assetSteps(asset),
    { title: '本次正式执行', description: executionId },
    {
      title: '独立核验收据',
      description: verified ? scenario.verification_status : '尚未完整封存，未核验',
    },
  ]
  return (
    <Card
      className="self-test-source-chain"
      size="small"
      title={fixed ? '固定基准来源链' : 'MCP 来源链'}
    >
      <Steps
        orientation="vertical"
        size="small"
        current={-1}
        items={items.map((item, index) => ({
          ...item,
          icon: <span className="self-test-chain-number">{index + 1}</span>,
          status: 'wait',
        }))}
      />
      <Typography.Text type="secondary">
        节点显示真实关联和回执；完整性与结论以右侧独立核验为准。
      </Typography.Text>
    </Card>
  )
}
function designSteps({ batch, scenario }: SelfTestRelation) {
  const source = scenario.source
  const fixed = batch.batch_kind === 'fixed_baseline'
  if (!source)
    return [
      {
        title: fixed ? '固定基准与期望' : '契约与期望',
        description: fixed ? batch.manifest_digest : '缺少生成来源，未核验',
      },
      { title: '真实 MCP 调用', description: fixed ? '固定基准不适用 MCP 调用链' : '尚无协议回执' },
      {
        title: 'Test Design / 场景',
        description: `${scenario.scenario_id} / ${scenario.variant_key}`,
      },
      { title: '受控提案', description: fixed ? '固定基准以冻结安装来源为准' : '缺少受控提案回执' },
    ]
  return sourceDesignSteps(source)
}
function sourceDesignSteps(source: SelfTestSource) {
  return [
    {
      title: '契约与期望',
      description: `${source.api_sources.length} 项固定 API 来源 · ${source.api_sources_digest}`,
    },
    { title: '真实 MCP 调用', description: source.protocol_receipts_digest },
    { title: 'Test Design / 场景', description: source.design_fingerprint },
    {
      title: '受控提案',
      description: `Workflow：${source.workflow_proposal.review_status}；Case：${source.case_proposal.review_status}`,
    },
  ]
}
function assetSteps(asset: SelfTestSource | SelfTestScenario['published_assets']) {
  if (!asset)
    return [
      { title: 'Workflow', description: '缺少固定版本来源' },
      { title: '原生 Case', description: '缺少固定版本来源' },
    ]
  return [
    { title: `Workflow v${asset.workflow.version}`, description: asset.workflow.id },
    { title: `原生 Case v${asset.case.version}`, description: asset.case.id },
  ]
}
