import { useMutation, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useState } from 'react'

import { apiErrorMessage } from '../../lib/api'
import { createProject, type CreateProjectInput } from './project-service'
import { useProjectContext } from './use-project-context'

export function useProjectCreator() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { selectProject } = useProjectContext()
  const [open, setOpen] = useState(false)
  const mutation = useMutation({ mutationFn: createProject })

  async function submit(input: CreateProjectInput) {
    try {
      const project = await mutation.mutateAsync(input)
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      setOpen(false)
      selectProject(project.id)
      void message.success('项目创建成功')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  return {
    open,
    setOpen,
    submitting: mutation.isPending,
    submit,
  }
}
