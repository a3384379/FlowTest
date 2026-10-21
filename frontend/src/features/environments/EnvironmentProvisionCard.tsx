import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Pagination,
  Select,
  Space,
  Typography,
} from 'antd'
import { useEffect, useState } from 'react'
import { apiErrorWithTrace } from '../../lib/api'
import { useAuthStore } from '../auth/auth-store'
import { getEnvironmentTemplateVersion, listEnvironmentTemplates } from './environment-service'
import './environment-lab.css'

type ProvisionForm = { template_version_id: string; ttl_seconds: number }
type ProvisionProps = {
  projectId: string | null
  enabled: boolean
  disabled: boolean
  submitting: boolean
  onProvision: (templateVersionId: string, ttlSeconds: number) => Promise<boolean>
}
export default function EnvironmentProvisionCard(props: ProvisionProps) {
  const state = useProvisionPicker(props.projectId, props.enabled)
  return (
    <Card title="Provision 受控环境" className="performance-card">
      <ProvisionSearch state={state} enabled={props.enabled} submitting={props.submitting} />
      {state.catalog.isError && (
        <Alert
          type="error"
          title="可用模板读取失败"
          description={apiErrorWithTrace(state.catalog.error)}
          action={<Button onClick={() => void state.catalog.refetch()}>重试可用模板</Button>}
        />
      )}
      <Pagination
        size="small"
        current={state.page}
        pageSize={20}
        total={catalogTotal(state.catalog.data)}
        showSizeChanger={false}
        onChange={state.setPage}
        showTotal={(total) => `共${total}个可用版本`}
      />
      <ProvisionFields state={state} {...props} />
      <SelectedVersionRead state={state} />
    </Card>
  )
}
function catalogTotal(data: { total: number } | undefined) {
  return data?.total ?? 0
}
function useProvisionPicker(projectId: string | null, enabled: boolean) {
  const [form] = Form.useForm<ProvisionForm>()
  const userId = useAuthStore((state) => state.user?.id)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [lookup, setLookup] = useState('')
  const versionId = Form.useWatch('template_version_id', form)
  const catalog = useQuery({
    queryKey: ['environment-templates', userId, 'provision', projectId, search, page],
    queryFn: () => listEnvironmentTemplates(page, { search, activeOnly: true }),
    enabled: enabled && Boolean(projectId),
  })
  const selected = useQuery({
    queryKey: ['environment-template-version', userId, projectId, versionId],
    queryFn: () => getEnvironmentTemplateVersion(versionId),
    enabled: enabled && Boolean(projectId && versionId),
  })
  useEffect(() => {
    if (selected.data?.status === 'active')
      form.setFieldValue('ttl_seconds', selected.data.manifest.default_ttl_seconds)
  }, [selected.data, form])
  const ready = selected.isSuccess && selected.data.status === 'active'
  return { form, page, setPage, setSearch, lookup, setLookup, versionId, catalog, selected, ready }
}
type PickerState = ReturnType<typeof useProvisionPicker>
function ProvisionSearch({
  state,
  enabled,
  submitting,
}: {
  state: PickerState
  enabled: boolean
  submitting: boolean
}) {
  const validUUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    state.lookup,
  )
  const inactive = !enabled || submitting
  return (
    <Space wrap>
      <Input.Search
        aria-label="查找可用模板"
        placeholder="按名称、标识或说明查找"
        onSearch={(value) => {
          state.setSearch(value)
          state.setPage(1)
        }}
        disabled={inactive}
      />
      <Input
        aria-label="模板版本ID"
        placeholder="或输入准确模板版本UUID"
        value={state.lookup}
        onChange={(event) => state.setLookup(event.target.value)}
        disabled={inactive}
      />
      <Button
        disabled={inactive || !validUUID}
        onClick={() => state.form.setFieldValue('template_version_id', state.lookup)}
      >
        读取指定版本
      </Button>
    </Space>
  )
}
function provisionChoices(state: PickerState) {
  const rows = state.catalog.data?.items ?? []
  const selected = state.selected.data
  const choices =
    selected && !rows.some((item) => item.id === selected.id) ? [selected, ...rows] : rows
  return choices.map((item) => ({
    value: item.id,
    label: `${item.display_name} · v${item.version}`,
    disabled: item.status !== 'active',
  }))
}
function ProvisionFields({
  state,
  disabled,
  submitting,
  onProvision,
}: ProvisionProps & { state: PickerState }) {
  const maximum = state.selected.data?.manifest.maximum_ttl_seconds ?? 86400
  return (
    <Form
      form={state.form}
      name="environment-provision"
      layout="inline"
      className="environment-provision-form"
      initialValues={{ ttl_seconds: 3600 }}
      disabled={disabled || submitting}
      onFinish={(value) => {
        if (state.ready) void onProvision(value.template_version_id, value.ttl_seconds)
      }}
    >
      <Form.Item
        name="template_version_id"
        label="模板版本"
        rules={[{ required: true, message: '请选择模板版本' }]}
      >
        <Select
          aria-label="模板版本"
          className="environment-template-select"
          placeholder="选择管理员签名模板"
          loading={state.catalog.isPending || state.selected.isFetching}
          options={provisionChoices(state)}
        />
      </Form.Item>
      <Form.Item
        name="ttl_seconds"
        label="TTL（秒）"
        rules={[
          { required: true },
          { type: 'number', min: 60, max: maximum, message: 'TTL超过所选版本允许范围' },
        ]}
      >
        <InputNumber min={60} max={maximum} precision={0} />
      </Form.Item>
      <Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          loading={submitting}
          disabled={disabled || !state.ready}
        >
          Provision
        </Button>
      </Form.Item>
    </Form>
  )
}
function SelectedVersionRead({ state }: { state: PickerState }) {
  if (state.selected.isError)
    return (
      <Alert
        type="error"
        title="指定模板版本读取失败"
        description={
          <>
            {state.versionId} · {apiErrorWithTrace(state.selected.error)}
          </>
        }
        action={<Button onClick={() => void state.selected.refetch()}>重试指定版本</Button>}
      />
    )
  const template = state.selected.data
  if (!template) return null
  if (template.status === 'disabled')
    return <Alert type="warning" title="此模板已停用，不能Provision，请重新选择可用版本" />
  return (
    <Typography.Text type="secondary">
      固定版本 {template.id} · 最大TTL {template.manifest.maximum_ttl_seconds}秒 ·
      只在点击Provision后入队
    </Typography.Text>
  )
}
