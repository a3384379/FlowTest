import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Collapse, Descriptions, Drawer, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import ResponseCodeReader from '../api-console/ResponseCodeReader'
import { DesignPreview } from './MCPStructuredPreview'
import { getMCPMaterializedDesign, type MCPChangeItem } from './mcp-change-set-service'

export default function MCPMaterializedResult({
  item,
  projectId,
  changeSetId,
}: {
  item: MCPChangeItem
  projectId: string
  changeSetId: string
}) {
  if (item.review_status !== 'accepted') return null
  const id = item.materialized_resource_id
  if (!id) return <Alert type="warning" title="已审核，但服务器未提供物化结果定位" />
  if (item.item_type === 'test_design' && item.materialized_resource_type === 'test_design')
    return (
      <MaterializedDesign
        itemId={item.id}
        designId={id}
        projectId={projectId}
        changeSetId={changeSetId}
      />
    )
  const result = resultPath(item, projectId, id)
  if (!result) return <Alert type="warning" title="物化结果类型与变更项不匹配，无法提供安全定位" />
  return (
    <Typography.Paragraph>
      <Link to={result.path}>{result.label}</Link>
      <Typography.Text code>{id}</Typography.Text>
    </Typography.Paragraph>
  )
}

function resultPath(
  item: MCPChangeItem,
  projectId: string,
  id: string,
): { path: string; label: string } | null {
  const encoded = encodeURIComponent(id)
  if (item.item_type === 'test_case' && item.materialized_resource_type === 'test_case')
    return {
      path: `/projects/${projectId}/assets?type=case&focus=${encoded}&version=draft`,
      label: '查看物化测试用例',
    }
  if (item.item_type === 'test_plan_update' && item.materialized_resource_type === 'test_plan')
    return { path: `/projects/${projectId}/tasks?focus=${encoded}`, label: '查看更新后的计划' }
  if (item.item_type === 'workflow' && item.materialized_resource_type === 'workflow')
    return {
      path: `/projects/${projectId}/workflows?focus=${encoded}`,
      label: item.action === 'create' ? '查看已创建草稿' : '查看物化工作流',
    }
  return null
}

function MaterializedDesign({
  itemId,
  designId,
  projectId,
  changeSetId,
}: {
  itemId: string
  designId: string
  projectId: string
  changeSetId: string
}) {
  const [open, setOpen] = useState(false)
  const query = useQuery({
    queryKey: ['mcp-materialized-design', projectId, changeSetId, itemId, designId],
    queryFn: async () => {
      const result = await getMCPMaterializedDesign(changeSetId, itemId)
      if (
        result.id !== designId ||
        result.project_id !== projectId ||
        result.source_change_set_id !== changeSetId
      )
        throw new Error('物化测试设计不属于当前变更集或项目，请核对来源。')
      return result
    },
    enabled: open,
  })
  return (
    <>
      <Button onClick={() => setOpen(true)}>查看已物化测试设计</Button>
      <Typography.Text code>{designId}</Typography.Text>
      <Drawer
        title="已物化测试设计（只读）"
        open={open}
        onClose={() => setOpen(false)}
        size="min(1080px, 100vw)"
      >
        <Alert type="info" title="读取实际保存的测试设计，不执行生成、审核或 Apply" />
        <QueryFailureNotice queries={[query]} />
        {query.isPending && <Typography.Text>正在读取已保存设计</Typography.Text>}
        {query.isError && query.data && (
          <Alert type="warning" title="资产刷新失败，以下为上次成功读取的保存记录" />
        )}
        {query.data && (
          <>
            <Descriptions
              column={1}
              items={[
                { label: '资产 ID', children: query.data.id },
                { label: '名称', children: query.data.name },
                { label: '状态', children: query.data.status },
                {
                  label: '内容指纹',
                  children: <Typography.Text copyable>{query.data.fingerprint}</Typography.Text>,
                },
                { label: '审核人 ID', children: query.data.reviewed_by_id ?? '未提供' },
                { label: '审核时间', children: query.data.reviewed_at ?? '未提供' },
              ]}
            />
            <DesignPreview content={query.data.design} />
            <Collapse
              items={[
                {
                  key: 'saved',
                  label: '完整已保存设计',
                  children: <ResponseCodeReader title="完整已保存设计" value={query.data.design} />,
                },
              ]}
            />
          </>
        )}
      </Drawer>
    </>
  )
}
