import { Alert, Card, Descriptions, Space, Tag, Typography } from 'antd'
import type { SelfTestGeneration, SelfTestBatch } from './self-test-contract'
import { generationModeLabels, readinessLabels } from './self-test-labels'
import { SelfTestArtifacts, SelfTestReasons, SelfTestSourceEvidence } from './SelfTestEvidence'
import SelfTestGenerationProgress from './SelfTestGenerationProgress'

export default function SelfTestGeneration({
  projectId,
  generation,
  batch,
}: {
  projectId: string
  generation: SelfTestGeneration
  batch: SelfTestBatch
}) {
  return (
    <Card title="MCP 生成与正式产物">
      <SelfTestGenerationProgress projectId={projectId} generation={generation} batch={batch} />
      <div className="self-test-generation">
        <div>
          <Space wrap>
            <Tag>
              {generation.generation_mode
                ? generationModeLabels[generation.generation_mode]
                : '生成模式未提供'}
            </Tag>
            <Tag color={generation.readiness === 'blocked' ? 'error' : undefined}>
              {readinessLabels[generation.readiness]}
            </Tag>
          </Space>
          {generation.generation_mode === 'deterministic_mcp' && (
            <Alert
              type="info"
              showIcon
              title="真实宿主模型链路：未执行（NOT_RUN）"
              description="当前批次使用确定性 MCP。模型验收需要另建已授权的宿主模型批次。"
            />
          )}
          <SelfTestReasons reasons={generation.reason_codes} />
          <Typography.Paragraph type="secondary">
            生成任务只准备提案。人工审核、发布固定版本和正式执行分别完成。
          </Typography.Paragraph>
          {!generation.sources.length ? (
            <SelfTestSourceEvidence
              projectId={projectId}
              batchId={generation.batch_id}
              source={null}
            />
          ) : (
            generation.sources.map((source) => (
              <SelfTestSourceEvidence
                key={`${source.scenario_id}:${source.variant_key}`}
                projectId={projectId}
                batchId={generation.batch_id}
                source={source}
              />
            ))
          )}
        </div>
        <div>
          <Descriptions
            size="small"
            column={1}
            items={[
              {
                key: 'host',
                label: '生成宿主',
                children:
                  generation.host_status === 'available'
                    ? '已登记'
                    : generation.host_status === 'expired'
                      ? '登记已过期'
                      : '未登记，等待外部宿主',
              },
              { key: 'calls', label: '实际工具调用', children: generation.tool_call_count },
              { key: 'published', label: '已发布来源', children: generation.sources.length },
            ]}
          />
          {generation.manifest && (
            <SelfTestArtifacts
              projectId={projectId}
              batchId={generation.batch_id}
              artifacts={[generation.manifest]}
            />
          )}
        </div>
      </div>
    </Card>
  )
}
