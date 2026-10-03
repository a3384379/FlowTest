import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Modal, Space, Tag, Typography } from 'antd'
import { apiErrorMessage } from '../../lib/api'
import {
  deleteTestAssets,
  deletionScopeMatches,
  previewAssetDeletion,
  type AssetDeletionPreview,
  type AssetReference,
} from './asset-deletion-service'
import type { AssetKind } from './asset-workspace-service'

export default function AssetDeletionDialog({
  projectId,
  kind,
  ids,
  canEdit,
  onClose,
  onDeleted,
}: {
  projectId: string
  kind: AssetKind
  ids: string[]
  canEdit: boolean
  onClose: () => void
  onDeleted: (ids: string[]) => void
}) {
  const client = useQueryClient()
  const preview = useQuery({
    queryKey: ['test-asset-deletion-preview', projectId, kind, ids],
    queryFn: () => previewAssetDeletion(projectId, kind, ids),
    enabled: canEdit,
    staleTime: 0,
  })
  const targets = preview.data?.targets ?? []
  const scopeMatches = deletionScopeMatches(
    ids,
    targets.map((item) => item.asset.id),
  )
  const blocked = targets.some((item) => item.references.length > 0)
  const deletion = useMutation({
    mutationFn: () =>
      deleteTestAssets(
        projectId,
        kind,
        targets.map((item) => item.asset),
      ),
    onSuccess: async (result) => {
      await Promise.all(
        [
          'test-cases',
          'test-suites',
          'test-asset',
          'asset-directory-counts',
          'test-suite-latest-runs',
        ].map((key) => client.invalidateQueries({ queryKey: [key, projectId] })),
      )
      onDeleted(result.archived_ids)
    },
  })
  return (
    <Modal
      open
      destroyOnHidden
      title={`删除${kind === 'case' ? '测试用例' : '测试套件'}（${ids.length} 项）`}
      onCancel={onClose}
      onOk={() => deletion.mutate()}
      okText={`确认删除 ${ids.length} 项`}
      cancelText="取消"
      confirmLoading={deletion.isPending}
      closable={!deletion.isPending}
      cancelButtonProps={{ disabled: deletion.isPending }}
      mask={{ closable: !deletion.isPending }}
      okButtonProps={{
        danger: true,
        disabled: !canDelete(
          canEdit,
          preview.isFetching,
          preview.error,
          scopeMatches,
          blocked,
          Boolean(deletion.error),
        ),
      }}
    >
      <Typography.Paragraph>
        删除仅影响下方确认的资产。已发布版本、执行历史和报告将保留；列表中的对象会被移除。
      </Typography.Paragraph>
      {!canEdit && <Alert type="warning" title="当前成员没有资产编辑权限" />}
      <PreviewStatus
        loading={preview.isPending}
        error={preview.error}
        scopeMatches={scopeMatches}
      />
      <DeletionTargets targets={targets} />
      {blocked && (
        <Alert
          type="warning"
          showIcon
          title="选中资产仍有引用，整批不能删除"
          description="请先处理列出的套件、计划或活动执行，再刷新预览。"
        />
      )}
      {deletion.error && (
        <Alert
          type="error"
          showIcon
          title="删除未完成"
          description={apiErrorMessage(deletion.error)}
        />
      )}
      <Button
        size="small"
        aria-label="刷新删除预览"
        disabled={!canEdit || deletion.isPending}
        loading={preview.isFetching}
        onClick={() => {
          deletion.reset()
          void preview.refetch()
        }}
      >
        刷新预览
      </Button>
    </Modal>
  )
}

function canDelete(
  canEdit: boolean,
  loading: boolean,
  error: Error | null,
  scopeMatches: boolean,
  blocked: boolean,
  requiresRefresh: boolean,
): boolean {
  return canEdit && !loading && !error && scopeMatches && !blocked && !requiresRefresh
}

function PreviewStatus({
  loading,
  error,
  scopeMatches,
}: {
  loading: boolean
  error: Error | null
  scopeMatches: boolean
}) {
  if (error)
    return <Alert type="error" title="删除预览读取失败" description={apiErrorMessage(error)} />
  if (loading)
    return <Typography.Paragraph type="secondary">正在核对选中资产和引用关系…</Typography.Paragraph>
  if (!scopeMatches) return <Alert type="error" title="预览范围与选择不一致，请刷新预览" />
  return null
}

function DeletionTargets({ targets }: AssetDeletionPreview) {
  return (
    <ul className="asset-deletion-list">
      {targets.map((item) => (
        <li key={item.asset.id}>
          <Space wrap>
            <Typography.Text strong>{item.asset.expected_name}</Typography.Text>
            <Tag>
              {item.asset.expected_version === null
                ? '未发布'
                : `已发布 v${item.asset.expected_version}`}
            </Tag>
            {item.archived && <Tag>已经删除</Tag>}
          </Space>
          <Typography.Paragraph type="secondary" copyable>
            {item.asset.id}
          </Typography.Paragraph>
          {item.references.map((reference, index) => (
            <ReferenceLabel
              key={`${reference.kind}:${reference.id}:${index}`}
              reference={reference}
            />
          ))}
        </li>
      ))}
    </ul>
  )
}

function ReferenceLabel({ reference }: { reference: AssetReference }) {
  const labels = { test_plan: '测试计划', test_suite: '测试套件', execution: '活动执行' }
  return (
    <Typography.Paragraph type="warning">
      {labels[reference.kind]}：{reference.name ?? reference.id}
      {reference.version !== null && ` · v${reference.version}`}
    </Typography.Paragraph>
  )
}
