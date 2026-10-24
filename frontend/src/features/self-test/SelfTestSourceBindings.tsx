import { Descriptions, Table, Typography } from 'antd'
import type { SelfTestSource } from './self-test-contract'
import SelfTestAssistedSource from './SelfTestAssistedSource'
export default function SelfTestSourceBindings({
  source,
  projectId,
}: {
  source: SelfTestSource
  projectId: string
}) {
  return (
    <div className="self-test-evidence">
      <SelfTestAssistedSource source={source} projectId={projectId} />
      {source.host_evidence && (
        <Descriptions
          title="宿主生成来源"
          size="small"
          column={1}
          items={[
            { key: 'host', label: '已登记宿主', children: source.host_evidence.host },
            { key: 'model', label: '模型', children: source.host_evidence.model },
            { key: 'skill', label: '技能摘要', children: source.host_evidence.skill_digest },
            { key: 'prompt', label: '提示词摘要', children: source.host_evidence.prompt_digest },
            {
              key: 'budget',
              label: '授权预算摘要',
              children: source.host_evidence.authorized_budget_digest,
            },
            {
              key: 'calls',
              label: '实际工具调用',
              children: source.host_evidence.actual_tool_calls,
            },
          ]}
        />
      )}
      <Typography.Text strong>API 来源固定版本</Typography.Text>
      <Table
        size="small"
        pagination={false}
        scroll={{ x: 700 }}
        rowKey={(row) => `${row.project_id}:${row.api_definition_id}:${row.api_version}`}
        dataSource={source.api_sources}
        columns={[
          { title: '项目', dataIndex: 'project_id' },
          { title: 'API', dataIndex: 'api_definition_id' },
          { title: '版本', dataIndex: 'api_version' },
          { title: '契约摘要', dataIndex: 'contract_fingerprint' },
        ]}
      />
      <Typography.Text strong>冻结 Oracle 与断言节点映射</Typography.Text>
      <Table
        size="small"
        pagination={{ pageSize: 10, showSizeChanger: false }}
        scroll={{ x: 900 }}
        rowKey={(row) => `${row.oracle_id}:${row.node_id}:${row.phase}`}
        dataSource={source.oracle_bindings}
        columns={[
          { title: 'Oracle', dataIndex: 'oracle_id' },
          { title: '节点', dataIndex: 'node_id' },
          { title: '阶段', dataIndex: 'phase' },
          { title: '断言名', dataIndex: 'assertion_name' },
          { title: '表达式', dataIndex: 'expression' },
          { title: '期望值摘要', dataIndex: 'expected_value_digest' },
        ]}
      />
    </div>
  )
}
