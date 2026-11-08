import SelfTestInstallationRecovery from './SelfTestInstallationRecovery'
import { useState } from 'react'
import { Button, Descriptions, Drawer, Empty, Table } from 'antd'
import type { SelfTestInstallation } from './self-test-contract'
import { installationStatusLabels } from './self-test-labels'
import { SelfTestReasons } from './SelfTestEvidence'
import SelfTestAssetLink from './SelfTestAssetLink'

export function InstallationMappingDetails({
  installation,
  projectId,
}: {
  installation: SelfTestInstallation
  projectId: string
}) {
  const mapping = installation.mapping
  return (
    <>
      <Descriptions
        column={1}
        items={[
          { label: '安装 ID', children: installation.id },
          { label: '安装状态', children: installationStatusLabels[installation.status] },
          {
            label: '模板版本',
            children: `${installation.template_id}@${installation.template_version}`,
          },
          { label: '环境指纹', children: installation.environment_fingerprint },
          ...mappingDetails(mapping),
        ]}
      />
      <SelfTestReasons reasons={installation.reason_codes} />
      <Table
        size="small"
        pagination={false}
        scroll={{ x: 700 }}
        dataSource={mapping?.assets ?? []}
        rowKey={(row) => `${row.scenario_id}:${row.variant_key}`}
        locale={{
          emptyText: (
            <Empty description="宿主尚未回报固定资产映射；已创建但未回报的资源须按原 journal 核对。" />
          ),
        }}
        columns={[
          { title: '场景', render: (_, row) => `${row.scenario_id} / ${row.variant_key}` },
          {
            title: 'Workflow 固定版本',
            render: (_, row) => (
              <SelfTestAssetLink projectId={projectId} kind="workflow" asset={row.workflow} />
            ),
          },
          {
            title: 'Case 固定版本',
            render: (_, row) => (
              <SelfTestAssetLink projectId={projectId} kind="case" asset={row.case} />
            ),
          },
        ]}
      />
    </>
  )
}
export default function SelfTestInstallationDetails(props: {
  installation: SelfTestInstallation
  projectId: string
  allowed?: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button onClick={() => setOpen(true)}>查看安装</Button>
      <Drawer open={open} onClose={() => setOpen(false)} title="自测安装详情" size={880}>
        <InstallationMappingDetails {...props} />
        <SelfTestInstallationRecovery
          installation={props.installation}
          projectId={props.projectId}
          allowed={props.allowed ?? false}
        />
      </Drawer>
    </>
  )
}

function mappingDetails(mapping: SelfTestInstallation['mapping']) {
  if (!mapping)
    return ['固定环境', '目标环境', '目标项目', '目标实例', '目标构建'].map((label) => ({
      label,
      children: '尚未回报',
    }))
  return [
    { label: '固定环境', children: mapping.environment_id },
    { label: '目标环境', children: mapping.target_environment_id },
    { label: '目标项目', children: mapping.target_project_id },
    { label: '目标实例', children: mapping.target_instance_id },
    { label: '目标构建', children: mapping.target_build_digest },
  ]
}
