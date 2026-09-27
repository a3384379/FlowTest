import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { project, workflow, workflowDefinition } from '../../test/fixtures'
import { server } from '../../test/server'
import NativeWorkflowTransferDialog from './NativeWorkflowTransferDialog'
import type { NativeWorkflowDocument } from './workflow-service'

const document: NativeWorkflowDocument = {
  format_version: 'flowtest-workflow-native-v1',
  name: workflow.name,
  description: workflow.description,
  definition: workflowDefinition,
}

afterEach(() => vi.restoreAllMocks())

describe('NativeWorkflowTransferDialog', () => {
  it('exports the saved definition and imports it as a new unpublished draft', async () => {
    const onImported = vi.fn().mockResolvedValue(undefined)
    const createObjectUrl = vi.fn(() => 'blob:workflow')
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    server.use(
      http.get(`/api/v1/projects/${project.id}/workflows/${workflow.id}/native-export`, () =>
        HttpResponse.json(document),
      ),
      http.post(`/api/v1/projects/${project.id}/workflows/native-import`, async ({ request }) => {
        expect(await request.json()).toEqual({ ...document, name: `${document.name} 副本` })
        return HttpResponse.json(
          {
            ...workflow,
            id: 'imported-workflow',
            name: `${document.name} 副本`,
            current_version: null,
          },
          { status: 201 },
        )
      }),
    )
    render(
      <AntdApp>
        <NativeWorkflowTransferDialog
          open
          projectId={project.id}
          workflowId={workflow.id}
          canEdit
          onClose={vi.fn()}
          onImported={onImported}
        />
      </AntdApp>,
    )
    const browser = userEvent.setup()
    await browser.click(screen.getByRole('button', { name: '导出服务器草稿 JSON' }))
    await waitFor(() => expect(createObjectUrl).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('textbox', { name: '原生定义 JSON' })).toHaveValue(
      JSON.stringify(document, null, 2),
    )
    await browser.click(screen.getByRole('button', { name: /导入为新草稿/ }))
    await waitFor(() =>
      expect(onImported).toHaveBeenCalledWith(expect.objectContaining({ id: 'imported-workflow' })),
    )
  })

  it('rejects unsupported document versions before sending a request', async () => {
    const imported = vi.fn()
    render(
      <AntdApp>
        <NativeWorkflowTransferDialog
          open
          projectId={project.id}
          workflowId={null}
          canEdit
          onClose={vi.fn()}
          onImported={imported}
        />
      </AntdApp>,
    )
    fireEvent.change(screen.getByRole('textbox', { name: '原生定义 JSON' }), {
      target: { value: JSON.stringify({ ...document, format_version: 'other' }) },
    })
    await userEvent.setup().click(screen.getByRole('button', { name: /导入为新草稿/ }))
    expect(imported).not.toHaveBeenCalled()
    expect(
      await screen.findByText('需要 flowtest-workflow-native-v1 原生工作流定义'),
    ).toBeInTheDocument()
  })
})
