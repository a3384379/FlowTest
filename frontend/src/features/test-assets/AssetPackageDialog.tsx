import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Checkbox,
  Collapse,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { apiErrorMessage, type Environment, type Folder, type Workflow } from '../../lib/api'
import { listWorkflowVersions } from '../workflows/workflow-service'
import {
  applyAssetPackage,
  previewAssetPackage,
  readAndPreviewAssetPackage,
  type PackageAction,
  type PackageAsset,
  type PackageAssetPreview,
  type PackageBindings,
  type PackageChoice,
  type PackageImportResult,
  type PackagePreview,
  type TestAssetPackage,
} from './asset-package-service'
import type { AssetKind } from './asset-workspace-service'

export type AssetPackageResources = {
  workflows: Workflow[]
  environments: Environment[]
  folders: Folder[]
}

type DialogProps = {
  projectId: string
  canEdit: boolean
  resources: AssetPackageResources
  onClose: () => void
  onImported: (result: PackageImportResult) => void
}

function usePackageImport({ projectId, canEdit, onImported }: DialogProps) {
  const client = useQueryClient()
  const [document, setDocument] = useState<TestAssetPackage | null>(null)
  const [filename, setFilename] = useState('')
  const [choices, setChoices] = useState<Record<string, PackageChoice>>({})
  const [bindings, setBindings] = useState<PackageBindings>({})
  const [review, setReview] = useState<PackagePreview | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const read = useMutation({
    mutationFn: (file: File) => readAndPreviewAssetPackage(projectId, file),
    onSuccess: (loaded) => {
      setDocument(loaded.package)
      setReview(loaded.preview)
    },
  })
  const preview = useMutation({
    mutationFn: () => {
      if (!document) throw new Error('请先选择原生包')
      return previewAssetPackage(projectId, {
        package: document,
        choices: Object.values(choices),
        bindings,
      })
    },
    onSuccess: setReview,
  })
  const apply = useMutation({
    mutationFn: () => {
      if (!document || !review || !confirmed || !canEdit) throw new Error('请先预览并确认导入范围')
      return applyAssetPackage(
        projectId,
        { package: document, choices: Object.values(choices), bindings },
        review.fingerprint,
      )
    },
    onSuccess: (result) => onImported(result),
    onError: () => {
      setReview(null)
      setConfirmed(false)
    },
    onSettled: () =>
      Promise.all(
        [
          'test-cases',
          'test-suites',
          'test-asset',
          'test-case-versions',
          'test-suite-versions',
          'test-case-options',
          'asset-directory-counts',
        ].map((key) => client.invalidateQueries({ queryKey: [key, projectId] })),
      ),
  })
  function invalidateReview() {
    setReview(null)
    setConfirmed(false)
    preview.reset()
    apply.reset()
  }
  function chooseFile(file: File) {
    invalidateReview()
    setDocument(null)
    setChoices({})
    setBindings({})
    setFilename(file.name)
    read.mutate(file)
  }
  return {
    document,
    filename,
    choices,
    bindings,
    review,
    confirmed,
    read,
    preview,
    apply,
    busy: read.isPending || preview.isPending || apply.isPending || !canEdit,
    error: read.error ?? preview.error ?? apply.error,
    chooseFile,
    setConfirmed,
    changeChoice: (choice: PackageChoice) => {
      invalidateReview()
      setChoices((previous) => ({ ...previous, [`${choice.kind}:${choice.source_id}`]: choice }))
    },
    changeBindings: (next: PackageBindings) => {
      invalidateReview()
      setBindings(next)
    },
    refresh: () => {
      invalidateReview()
      read.reset()
      preview.mutate()
    },
  }
}

type PackageImportState = ReturnType<typeof usePackageImport>

export default function AssetPackageDialog(props: DialogProps) {
  const state = usePackageImport(props)
  return (
    <Modal
      open
      destroyOnHidden
      width={1050}
      title="导入测试资产原生包"
      onCancel={props.onClose}
      onOk={() => state.apply.mutate()}
      okText="确认导入"
      cancelText="取消"
      confirmLoading={state.apply.isPending}
      closable={!state.apply.isPending}
      mask={{ closable: !state.apply.isPending }}
      cancelButtonProps={{ disabled: state.apply.isPending }}
      okButtonProps={{
        disabled: !canImportPackage(
          state.review,
          state.confirmed,
          state.busy,
          props.canEdit,
          Boolean(state.error),
        ),
      }}
    >
      <Typography.Paragraph>
        包含用例与套件的草稿、已发布版本、目录引用、标签和模板属性。套件会关联导入或复用后的固定用例版本；历史版本保持不变。
      </Typography.Paragraph>
      <PackageReadState state={state} canEdit={props.canEdit} />
      {state.document && (
        <LoadedPackageEditor
          state={state}
          projectId={props.projectId}
          resources={props.resources}
        />
      )}
      <PackageReviewState state={state} />
    </Modal>
  )
}

function canImportPackage(
  review: PackagePreview | null,
  confirmed: boolean,
  busy: boolean,
  canEdit: boolean,
  error: boolean,
): boolean {
  return Boolean(review?.can_apply && confirmed && !busy && canEdit && !error)
}

function PackageReadState({ state, canEdit }: { state: PackageImportState; canEdit: boolean }) {
  return (
    <Space orientation="vertical" className="full-width">
      {!canEdit && <Alert type="warning" title="当前成员没有资产导入权限" />}
      <label>
        选择原生 JSON 文件
        <input
          type="file"
          accept=".json,application/json"
          aria-label="原生测试资产文件"
          disabled={!canEdit || state.busy}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) state.chooseFile(file)
            event.target.value = ''
          }}
        />
      </label>
      <Typography.Text type="secondary">文件上限 10 MiB。{state.filename}</Typography.Text>
      {state.read.isPending && <Typography.Text>正在校验原生包及同项目引用…</Typography.Text>}
      {state.error && (
        <Alert type="error" title="导入未完成" description={apiErrorMessage(state.error)} />
      )}
    </Space>
  )
}

function LoadedPackageEditor({
  state,
  projectId,
  resources,
}: {
  state: PackageImportState
  projectId: string
  resources: AssetPackageResources
}) {
  const document = state.document!
  return (
    <Space orientation="vertical" className="full-width">
      <Typography.Paragraph>
        共 {document.cases.length} 个用例、{document.suites.length} 个套件；来源项目{' '}
        {document.source_project_id}
      </Typography.Paragraph>
      <PackageAssetChoices document={document} state={state} />
      <Collapse
        items={[
          {
            key: 'bindings',
            label: '流程、环境与目录绑定',
            children: (
              <PackageResourceBindings
                projectId={projectId}
                document={document}
                resources={resources}
                state={state}
              />
            ),
          },
          {
            key: 'members',
            label: '套件固定引用',
            children: <PackageFixedReferences document={document} />,
          },
        ]}
        defaultActiveKey={['bindings']}
      />
      <Button disabled={state.busy} loading={state.preview.isPending} onClick={state.refresh}>
        重新预览导入
      </Button>
    </Space>
  )
}

function PackageAssetChoices({
  document,
  state,
}: {
  document: TestAssetPackage
  state: PackageImportState
}) {
  const assets = [
    ...document.cases.map((asset) => ({ ...asset, kind: 'case' as const })),
    ...document.suites.map((asset) => ({ ...asset, kind: 'suite' as const })),
  ]
  return (
    <Table
      size="small"
      dataSource={assets}
      rowKey={(asset) => `${asset.kind}:${asset.id}`}
      pagination={{ pageSize: 20, showSizeChanger: false }}
      columns={[
        {
          title: '原资产',
          render: (_, asset) => (
            <>
              <Tag>{asset.kind === 'case' ? '用例' : '套件'}</Tag>
              {asset.name} · {asset.versions.length} 个已发布版本
            </>
          ),
        },
        {
          title: '冲突策略与目标名称',
          render: (_, asset) => <PackageChoiceFields asset={asset} state={state} />,
        },
      ]}
    />
  )
}

function PackageChoiceFields({
  asset,
  state,
}: {
  asset: PackageAsset & { kind: AssetKind }
  state: PackageImportState
}) {
  const choice = state.choices[`${asset.kind}:${asset.id}`] ?? {
    kind: asset.kind,
    source_id: asset.id,
    action: 'create' as PackageAction,
  }
  const reviewed = state.review?.assets.find(
    (item) => item.kind === asset.kind && item.source_id === asset.id,
  )
  return (
    <Space orientation="vertical">
      <Select
        aria-label={`${asset.name}导入策略`}
        value={choice.action}
        disabled={state.busy}
        options={[
          { value: 'create', label: '新建' },
          { value: 'clone', label: '另存名称' },
          { value: 'update', label: '更新已有资产' },
          { value: 'skip', label: '跳过并复用已有版本' },
        ]}
        onChange={(action: PackageAction) =>
          state.changeChoice({ ...choice, action, target_id: undefined })
        }
      />
      <Input
        aria-label={`${asset.name}目标名称`}
        value={choice.name ?? asset.name}
        maxLength={200}
        disabled={state.busy || choice.action === 'skip'}
        onChange={(event) =>
          state.changeChoice({
            ...choice,
            name: event.target.value,
            target_id: updateTargetId(choice, reviewed),
          })
        }
      />
    </Space>
  )
}

function updateTargetId(
  choice: PackageChoice,
  reviewed: PackageAssetPreview | undefined,
): string | undefined {
  if (choice.action !== 'update') return undefined
  return choice.target_id ?? reviewed?.target_id ?? undefined
}

function PackageResourceBindings({
  projectId,
  document,
  resources,
  state,
}: {
  projectId: string
  document: TestAssetPackage
  resources: AssetPackageResources
  state: PackageImportState
}) {
  return (
    <Space orientation="vertical" className="full-width">
      {document.workflows.map((workflow) => (
        <PackageWorkflowBinding
          key={workflow.id}
          projectId={projectId}
          source={workflow}
          workflows={resources.workflows}
          state={state}
        />
      ))}
      {document.environments.map((source) => (
        <label key={source.id}>
          环境：{source.name}
          <Select
            aria-label={`${source.name}环境绑定`}
            value={state.bindings.environments?.[source.id] ?? source.id}
            disabled={state.busy}
            options={resources.environments.map((item) => ({ value: item.id, label: item.name }))}
            onChange={(id: string) =>
              state.changeBindings({
                ...state.bindings,
                environments: { ...state.bindings.environments, [source.id]: id },
              })
            }
          />
        </label>
      ))}
      {document.folders.map((source) => (
        <label key={source.id}>
          目录：{source.name}
          <Select
            aria-label={`${source.name}目录绑定`}
            value={folderBindingValue(state.bindings, source.id)}
            disabled={state.busy}
            options={[
              { value: 'unfiled', label: '未分类' },
              ...resources.folders.map((item) => ({ value: item.id, label: item.name })),
            ]}
            onChange={(id: string) =>
              state.changeBindings({
                ...state.bindings,
                folders: { ...state.bindings.folders, [source.id]: id === 'unfiled' ? null : id },
              })
            }
          />
        </label>
      ))}
    </Space>
  )
}

function folderBindingValue(bindings: PackageBindings, id: string): string {
  if (bindings.folders?.[id] === null) return 'unfiled'
  return bindings.folders?.[id] ?? id
}

function PackageWorkflowBinding({
  projectId,
  source,
  workflows,
  state,
}: {
  projectId: string
  source: TestAssetPackage['workflows'][number]
  workflows: Workflow[]
  state: PackageImportState
}) {
  const binding = state.bindings.workflows?.[source.id] ?? { target_id: source.id, versions: {} }
  const versions = useQuery({
    queryKey: ['workflow-versions', projectId, binding.target_id, 'asset-import'],
    queryFn: () => listWorkflowVersions(projectId, binding.target_id),
    enabled: workflows.some((workflow) => workflow.id === binding.target_id),
  })
  function change(next: typeof binding) {
    state.changeBindings({
      ...state.bindings,
      workflows: { ...state.bindings.workflows, [source.id]: next },
    })
  }
  return (
    <Space wrap>
      <Typography.Text>流程：{source.name}</Typography.Text>
      <Select
        aria-label={`${source.name}流程绑定`}
        value={binding.target_id}
        disabled={state.busy}
        options={workflows.map((item) => ({ value: item.id, label: item.name }))}
        onChange={(id: string) => change({ target_id: id, versions: {} })}
      />
      {source.versions.map((version) => (
        <label key={version.version}>
          原 v{version.version} →
          <Select
            aria-label={`${source.name}原v${version.version}目标版本`}
            value={binding.versions[version.version] ?? version.version}
            loading={versions.isFetching}
            disabled={state.busy}
            options={(versions.data ?? []).map((candidate) => ({
              value: candidate.version,
              label: `已发布 v${candidate.version}`,
            }))}
            onChange={(number: number) =>
              change({ ...binding, versions: { ...binding.versions, [version.version]: number } })
            }
          />
        </label>
      ))}
      {versions.error && (
        <Alert
          type="error"
          title="流程版本读取失败"
          description={apiErrorMessage(versions.error)}
          action={<Button onClick={() => void versions.refetch()}>重新读取版本</Button>}
        />
      )}
    </Space>
  )
}

function PackageFixedReferences({ document }: { document: TestAssetPackage }) {
  const cases = new Map(document.cases.map((asset) => [asset.id, asset.name]))
  return (
    <ul>
      {document.suites.flatMap((suite) =>
        suite.versions.map((version) => (
          <li key={`${suite.id}:${version.version}`}>
            {suite.name} v{version.version}：
            {version.definition.items
              .map(
                (item) =>
                  `${cases.get(item.test_case_id) ?? item.test_case_id} v${item.test_case_version}`,
              )
              .join('、')}
          </li>
        )),
      )}
    </ul>
  )
}

function PackageReviewState({ state }: { state: PackageImportState }) {
  if (!state.review)
    return (
      <Typography.Paragraph type="secondary">
        选择文件并完成配置后，请重新预览。修改策略或绑定会使旧预览失效。
      </Typography.Paragraph>
    )
  const review = state.review
  return (
    <Space orientation="vertical" className="full-width">
      <Alert
        type={review.can_apply ? 'success' : 'warning'}
        title={review.can_apply ? '预览通过，请核对下方范围' : '存在冲突或缺失绑定，当前不能导入'}
      />
      <Table
        size="small"
        dataSource={review.assets}
        rowKey={(asset) => `${asset.kind}:${asset.source_id}`}
        pagination={{ pageSize: 20 }}
        columns={[
          {
            title: '目标资产',
            render: (_, asset) => (
              <>
                <strong>{asset.target_name}</strong>
                <br />
                {asset.target_id ?? '导入后新建'} · {actionLabel(asset.action)}
              </>
            ),
          },
          {
            title: '固定版本映射',
            render: (_, asset) =>
              asset.versions.map((version) => (
                <div key={version.source_version}>
                  原 v{version.source_version} → v{version.target_version}（
                  {version.creates_version ? '新增' : '复用'}）
                </div>
              )),
          },
          {
            title: '校验',
            render: (_, asset) =>
              asset.problems.map((problem) => (
                <Typography.Paragraph key={problem} type="danger">
                  {problem}
                </Typography.Paragraph>
              )),
          },
        ]}
      />
      <ul>
        {review.dependencies.map((dependency) => (
          <li key={`${dependency.kind}:${dependency.source_id}:${dependency.source_version}`}>
            {dependency.source_name} → {dependency.target_name ?? '尚未绑定'}
            <DependencyVersion item={dependency} />
            {dependency.fingerprint_changed && (
              <Tag color="orange">目标流程版本内容与原引用不同</Tag>
            )}
            {dependency.problems.map((problem) => (
              <Typography.Text key={problem} type="danger">
                {' '}
                · {problem}
              </Typography.Text>
            ))}
          </li>
        ))}
      </ul>
      <Checkbox
        checked={state.confirmed}
        disabled={state.busy || !review.can_apply}
        onChange={(event) => state.setConfirmed(event.target.checked)}
      >
        已核对资产、固定版本、覆盖范围及资源绑定，确认导入
      </Checkbox>
    </Space>
  )
}

function actionLabel(action: PackageAction): string {
  return {
    create: '新建',
    clone: '另存名称',
    update: '更新草稿并保留历史版本',
    skip: '跳过并复用已有版本',
  }[action]
}

function DependencyVersion({ item }: { item: PackagePreview['dependencies'][number] }) {
  if (item.source_version === null) return null
  return (
    <>
      {' '}
      · 原 v{item.source_version} → 目标 v{item.target_version}
    </>
  )
}
