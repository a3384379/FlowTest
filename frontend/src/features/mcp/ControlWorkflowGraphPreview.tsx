import { Button, Modal, Space, Tag, Typography } from 'antd'
import { useState } from 'react'

import WorkflowDesigner from '../../flow/WorkflowDesigner'
import type { WorkflowDefinition } from '../../lib/api'

export default function ControlWorkflowGraphPreview({
  definition,
  projectId,
  proposalId,
}: {
  definition: WorkflowDefinition
  projectId: string
  proposalId: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button onClick={() => setOpen(true)}>查看提案图</Button>
      <Modal
        title="新建控制流工作流提案"
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        width="90vw"
        destroyOnHidden
      >
        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          <Typography.Text type="secondary">
            仅预览待审核定义；人工接受后才会创建草稿，发布和执行需另行操作。
          </Typography.Text>
          <Space wrap>
            <Tag>主节点 {definition.nodes.length}</Tag>
            <Tag>主连线 {definition.edges.length}</Tag>
            <Tag>内联区域 {definition.regions?.length ?? 0}</Tag>
          </Space>
          <WorkflowDesigner
            mode="proposal"
            projectId={projectId}
            workflowId={proposalId}
            definition={definition}
            apis={[]}
            artifacts={[]}
            credentials={[]}
            statuses={{}}
            editable={false}
            onChange={() => undefined}
          />
        </Space>
      </Modal>
    </>
  )
}
