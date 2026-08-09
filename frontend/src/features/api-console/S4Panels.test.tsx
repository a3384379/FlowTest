import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import ArtifactPanel from './ArtifactPanel'
import ImportDialog from './ImportDialog'
import type { Artifact, ImportRun } from '../../lib/api'

const importRun: ImportRun = {
  id: 'import-1',
  project_id: 'project-1',
  source_type: 'openapi3',
  source_name: 'openapi.json',
  source_sha256: 'digest',
  added: 1,
  changed: 1,
  deleted: 1,
  unchanged: 1,
  results: [
    {
      import_key: 'key-1',
      name: '查询用户',
      method: 'GET',
      path: '/users',
      change: 'added',
      definition_id: 'api-1',
      version: 1,
    },
  ],
  created_at: '2026-08-09T00:00:00Z',
}

describe('S4 API console panels', () => {
  it('selects an import document and renders its diff', async () => {
    const onImport = vi.fn(async () => importRun)
    const onClose = vi.fn()
    const { rerender } = render(
      <ImportDialog open importing={false} result={null} onClose={onClose} onImport={onImport} />,
    )
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]')
    expect(fileInput).not.toBeNull()
    await userEvent.upload(
      fileInput!,
      new File(['{}'], 'openapi.json', { type: 'application/json' }),
    )
    await userEvent.click(screen.getByRole('button', { name: '开始导入' }))
    expect(onImport).toHaveBeenCalledWith(expect.objectContaining({ name: 'openapi.json' }))

    rerender(
      <ImportDialog
        open
        importing={false}
        result={importRun}
        onClose={onClose}
        onImport={onImport}
      />,
    )
    expect(screen.getByText('查询用户')).toBeInTheDocument()
    expect(screen.getAllByText('新增')).not.toHaveLength(0)
    expect(screen.getByText('待停用')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('uploads and downloads artifacts while formatting their sizes', async () => {
    const items: Artifact[] = [
      artifact('small.txt', 12, 'small'),
      artifact('medium.json', 2048, 'medium'),
      artifact('large.bin', 2 * 1024 * 1024, 'large', 'response'),
    ]
    const onUpload = vi.fn(async () => items[0])
    const onDownload = vi.fn(async () => undefined)
    const { container } = render(
      <ArtifactPanel
        disabled={false}
        loading={false}
        uploading={false}
        items={items}
        onUpload={onUpload}
        onDownload={onDownload}
      />,
    )
    expect(screen.getByText('12 B')).toBeVisible()
    expect(screen.getByText('2.0 KB')).toBeVisible()
    expect(screen.getByText('2.0 MB')).toBeVisible()
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]')
    await userEvent.upload(fileInput!, new File(['data'], 'new.txt', { type: 'text/plain' }))
    expect(onUpload).toHaveBeenCalled()
    await userEvent.click(screen.getAllByRole('button', { name: /下载/ })[0])
    expect(onDownload).toHaveBeenCalledWith('small')
  })
})

function artifact(
  filename: string,
  size: number,
  id: string,
  purpose: Artifact['purpose'] = 'upload',
): Artifact {
  return {
    id,
    project_id: 'project-1',
    filename,
    content_type: 'application/octet-stream',
    size_bytes: size,
    sha256: 'digest',
    purpose,
    created_at: '2026-08-09T00:00:00Z',
  }
}
