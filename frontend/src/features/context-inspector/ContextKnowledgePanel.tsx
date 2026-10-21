import { Alert, Button, Card, Descriptions, Empty, Flex, List, Space, Tag, Typography } from 'antd'
import type { KnowledgeNode } from './context-inspector-service'
import type { ContextEvidenceProps } from './ContextEvidenceBrowser'
import { evidenceReference } from './context-navigation'

export default function ContextKnowledgePanel({
  detail,
  selection,
  onNavigate,
}: ContextEvidenceProps) {
  const { nodes, edges } = detail.revision.knowledge_snapshot
  const selected = nodes.find((node) => node.id === selection.knowledge)
  const labels = new Map(nodes.map((node) => [node.id, node.label]))
  const related = selected
    ? edges.filter((edge) => edge.source === selected.id || edge.target === selected.id)
    : edges
  function selectNode(id: string) {
    onNavigate({ knowledge: id })
  }
  return (
    <Flex vertical gap={16}>
      <Card size="small" title={`State Knowledge · ${nodes.length} Nodes / ${edges.length} Edges`}>
        {nodes.length === 0 ? (
          <Empty description="暂无 State Candidate" />
        ) : (
          <List<KnowledgeNode>
            size="small"
            pagination={{ pageSize: 15, hideOnSinglePage: true }}
            dataSource={nodes}
            renderItem={(node) => (
              <List.Item
                actions={[
                  <Button
                    key="select"
                    type={node.id === selected?.id ? 'primary' : 'default'}
                    aria-label={`查看知识节点 ${node.id}`}
                    onClick={() => selectNode(node.id)}
                  >
                    查看节点
                  </Button>,
                ]}
              >
                <div>
                  <Typography.Text strong>{node.label}</Typography.Text> <Tag>{node.kind}</Tag>
                  <Typography.Paragraph type="secondary">
                    {node.facts.some(
                      (fact) => fact.name === 'requires_review' && fact.value === 'true',
                    )
                      ? '需复核'
                      : '未声明需复核'}
                  </Typography.Paragraph>
                </div>
              </List.Item>
            )}
          />
        )}
      </Card>
      {selection.knowledge && !selected ? (
        <Alert
          type="warning"
          title="指定知识节点不在当前固定修订中"
          description={selection.knowledge}
        />
      ) : null}
      {selected ? (
        <Card size="small" title={`知识节点：${selected.label}`}>
          <Typography.Text copyable>{selected.id}</Typography.Text>
          <Descriptions
            column={1}
            items={selected.facts.map((fact, index) => ({
              key: String(index),
              label: fact.name,
              children: (
                <Typography.Text style={{ overflowWrap: 'anywhere' }} copyable>
                  {fact.value}
                </Typography.Text>
              ),
            }))}
          />
          {selected.facts
            .filter((fact) => fact.name === 'evidence_ref')
            .map((fact, index) => {
              const evidence = evidenceReference(fact.value, detail.evidence_items)
              return evidence ? (
                <Button
                  key={index}
                  onClick={() =>
                    onNavigate({
                      panel: 'evidence',
                      evidence: evidence.id,
                      providerType: null,
                      certainty: null,
                      warnings: null,
                      conflict: null,
                      sourceEvidence: null,
                    })
                  }
                >
                  定位关联证据
                </Button>
              ) : (
                <Alert
                  key={index}
                  type="warning"
                  title="当前修订没有可唯一定位的证据引用"
                  description={fact.value}
                />
              )
            })}
        </Card>
      ) : null}
      <Card size="small" title="Knowledge Graph">
        <Typography.Paragraph>
          当前关系 {related.length} / 总关系 {edges.length}
        </Typography.Paragraph>
        {selected ? (
          <Button onClick={() => onNavigate({ knowledge: null })}>显示全部知识关系</Button>
        ) : null}
        <List
          size="small"
          pagination={{ pageSize: 15, hideOnSinglePage: true }}
          dataSource={related}
          renderItem={(edge) => (
            <List.Item>
              <Space wrap>
                {nodes.some((node) => node.id === edge.source) ? (
                  <Button type="link" onClick={() => selectNode(edge.source)}>
                    {labels.get(edge.source)}
                  </Button>
                ) : (
                  <Typography.Text>{edge.source}（节点未提供）</Typography.Text>
                )}
                <span aria-hidden>→</span>
                <Tag>{edge.relation}</Tag>
                <span aria-hidden>→</span>
                {nodes.some((node) => node.id === edge.target) ? (
                  <Button type="link" onClick={() => selectNode(edge.target)}>
                    {labels.get(edge.target)}
                  </Button>
                ) : (
                  <Typography.Text>{edge.target}（节点未提供）</Typography.Text>
                )}
              </Space>
            </List.Item>
          )}
        />
      </Card>
    </Flex>
  )
}
