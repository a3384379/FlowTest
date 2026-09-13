import { Button, Collapse, Space, Tag } from 'antd'
import type { EditDiagnostic } from './editor/editor-types'
export default function WorkflowDiagnostics({
  issues,
  onLocate,
  localDraft = true,
}: {
  issues: EditDiagnostic[]
  localDraft?: boolean
  onLocate: (issue: EditDiagnostic) => void
}) {
  if (!issues.length) return <Tag color="success">流程结构检查通过</Tag>
  return (
    <Collapse
      size="small"
      items={[
        {
          key: 'structure',
          label: localDraft
            ? `流程结构待完善（${issues.length}）· 本地修改已保留`
            : `流程结构提示（${issues.length}）`,
          children: (
            <Space orientation="vertical" align="start">
              {issues.map((issue, index) => (
                <Button key={`${issue.code}-${index}`} type="link" onClick={() => onLocate(issue)}>
                  {issue.message}
                  {issue.nodeId ? `（${issue.nodeId}）` : ''}
                </Button>
              ))}
            </Space>
          ),
        },
      ]}
    />
  )
}
