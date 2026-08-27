import { Button, Empty } from 'antd'

import CreateProjectDialog from './CreateProjectDialog'
import { useProjectCreator } from './use-project-creator'

export default function ProjectEmptyState() {
  const creator = useProjectCreator()
  return (
    <>
      <Empty description="暂无可访问项目">
        <Button type="primary" onClick={() => creator.setOpen(true)}>
          创建第一个项目
        </Button>
      </Empty>
      {creator.open && (
        <CreateProjectDialog
          open
          submitting={creator.submitting}
          onClose={() => creator.setOpen(false)}
          onCreate={creator.submit}
        />
      )}
    </>
  )
}
