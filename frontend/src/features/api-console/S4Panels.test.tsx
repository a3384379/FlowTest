import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import ArtifactPanel from './ArtifactPanel'
import ImportDialog from './ImportDialog'
import type { Artifact, ImportRun } from '../../lib/api'

const importRun: ImportRun = {
  id: 'import-1',
  project_id: 'project-1',
  source_kind: 'file',
  source_key: 'file:openapi.json',
  source_type: 'openapi3',
  source_name: 'openapi.json',
  source_url: null,
  document_url: null,
  source_sha256: 'digest',
  added: 1,
  changed: 1,
  deleted: 1,
  unchanged: 1,
  status: 'preview',
  applied_keys: [],
  applied_at: null,
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
    const onPreview = vi.fn(async () => importRun)
    const onMerge = vi.fn(async () => ({ ...importRun, status: 'applied' as const }))
    const onClose = vi.fn()
    const { rerender } = render(
      <ImportDialog
        open
        importing={false}
        result={null}
        onClose={onClose}
        onDiscover={vi.fn()}
        onPreview={onPreview}
        onMerge={onMerge}
      />,
    )
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]')
    expect(fileInput).not.toBeNull()
    await userEvent.upload(
      fileInput!,
      new File(['{}'], 'openapi.json', { type: 'application/json' }),
    )
    await userEvent.click(screen.getByRole('button', { name: '生成 Diff' }))
    expect(onPreview).toHaveBeenCalledWith({
      kind: 'file',
      file: expect.objectContaining({ name: 'openapi.json' }),
      sourceType: 'auto',
    })

    rerender(
      <ImportDialog
        open
        importing={false}
        result={importRun}
        onClose={onClose}
        onDiscover={vi.fn()}
        onPreview={onPreview}
        onMerge={onMerge}
      />,
    )
    expect(screen.getByText('查询用户')).toBeInTheDocument()
    expect(screen.getAllByText('新增')).not.toHaveLength(0)
    expect(screen.getByText('待停用')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '合并所选' }))
    expect(onMerge).toHaveBeenCalledWith(['key-1'])
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('accepts an OpenAPI URL and shows its source in the diff', async () => {
    const documentId = 'a'.repeat(64)
    const onDiscover = vi.fn(async () => ({
      source_url: 'https://api.example.com/openapi.json',
      source_kind: 'document' as const,
      documents: [
        {
          id: documentId,
          name: 'openapi.json',
          url: 'https://api.example.com/openapi.json',
        },
      ],
    }))
    const onPreview = vi.fn(async () => importRun)
    const onMerge = vi.fn(async () => importRun)
    const { rerender } = render(
      <ImportDialog
        open
        importing={false}
        result={null}
        onClose={vi.fn()}
        onDiscover={onDiscover}
        onPreview={onPreview}
        onMerge={onMerge}
      />,
    )

    await userEvent.click(screen.getByText('URL 导入'))
    const generate = screen.getByRole('button', { name: '解析并生成 Diff' })
    expect(generate).toBeDisabled()
    await userEvent.type(screen.getByLabelText('文档或 Swagger UI URL'), 'not-a-url')
    expect(screen.getByText('请输入有效的 HTTP 或 HTTPS 地址')).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText('文档或 Swagger UI URL'))
    await userEvent.type(
      screen.getByLabelText('文档或 Swagger UI URL'),
      'https://api.example.com/openapi.json',
    )
    await userEvent.click(generate)
    await waitFor(() =>
      expect(onPreview).toHaveBeenCalledWith({
        kind: 'url',
        url: 'https://api.example.com/openapi.json',
        sourceType: 'auto',
        documentId,
      }),
    )

    rerender(
      <ImportDialog
        open
        importing={false}
        result={{
          ...importRun,
          source_kind: 'url',
          source_key: 'url:digest',
          source_url: 'https://api.example.com/openapi.json',
          document_url: 'https://api.example.com/openapi.json',
        }}
        onClose={vi.fn()}
        onDiscover={onDiscover}
        onPreview={onPreview}
        onMerge={onMerge}
      />,
    )
    expect(screen.getByText('来源页面：https://api.example.com/openapi.json')).toBeInTheDocument()
  })

  it('discovers and selects a Swagger UI document group before preview', async () => {
    const usersId = 'a'.repeat(64)
    const ordersId = 'b'.repeat(64)
    const onDiscover = vi.fn(async () => ({
      source_url: 'https://api.example.com/swagger-ui/index.html',
      source_kind: 'swagger_ui' as const,
      documents: [
        { id: usersId, name: '用户服务', url: 'https://api.example.com/v3/api-docs/users' },
        { id: ordersId, name: '订单服务', url: 'https://api.example.com/v3/api-docs/orders' },
      ],
    }))
    const onPreview = vi.fn(async () => importRun)
    render(
      <ImportDialog
        open
        importing={false}
        result={null}
        onClose={vi.fn()}
        onDiscover={onDiscover}
        onPreview={onPreview}
        onMerge={vi.fn(async () => importRun)}
      />,
    )

    await userEvent.click(screen.getByText('URL 导入'))
    await userEvent.type(
      screen.getByLabelText('文档或 Swagger UI URL'),
      'https://api.example.com/swagger-ui/index.html',
    )
    await userEvent.click(screen.getByRole('button', { name: '解析并生成 Diff' }))
    expect(await screen.findByText('已发现 2 份接口文档')).toBeInTheDocument()
    expect(onPreview).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '生成 Diff' })).toBeDisabled()

    await userEvent.click(screen.getByText('订单服务'))
    await userEvent.click(screen.getByRole('button', { name: '生成 Diff' }))
    await waitFor(() =>
      expect(onPreview).toHaveBeenCalledWith({
        kind: 'url',
        url: 'https://api.example.com/swagger-ui/index.html',
        sourceType: 'auto',
        documentId: ordersId,
      }),
    )
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
