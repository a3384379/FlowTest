import { useMutation, useQueryClient } from '@tanstack/react-query'
import { App, Form, Input, Modal, Typography } from 'antd'
import { useLayoutEffect, useRef } from 'react'

import { apiErrorWithTrace, type MockService } from '../../lib/api'
import { updateMockService } from './data-source-service'

export default function MockServiceEditor({
  projectId,
  service,
  canEdit,
  onClose,
}: {
  projectId: string
  service: MockService
  canEdit: boolean
  onClose: () => void
}) {
  const [form] = Form.useForm<{ name: string; description: string }>()
  const queryClient = useQueryClient()
  const { message } = App.useApp()
  const active = useRef(true)
  useLayoutEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  const save = useMutation({
    mutationFn: (input: { name: string; description: string }) =>
      updateMockService(projectId, service.id, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['mock-services', projectId] })
      if (!active.current) return
      void message.success('Mock 服务已更新')
      onClose()
    },
    onError: (error) => {
      if (active.current) void message.error(apiErrorWithTrace(error))
    },
  })
  return (
    <Modal
      title="编辑 Mock 服务"
      aria-label="编辑 Mock 服务"
      open
      onCancel={onClose}
      onOk={() => form.submit()}
      okText="保存服务"
      cancelText="取消"
      okButtonProps={{ disabled: !canEdit, loading: save.isPending }}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        访问标识创建后保持不变，已有调用地址继续有效。
      </Typography.Paragraph>
      <Typography.Paragraph code>{service.slug}</Typography.Paragraph>
      <Form
        form={form}
        layout="vertical"
        disabled={!canEdit || save.isPending}
        initialValues={{ name: service.name, description: service.description }}
        onFinish={(values) => {
          if (canEdit && !save.isPending) save.mutate(values)
        }}
      >
        <Form.Item name="name" label="服务名称" rules={[{ required: true, whitespace: true }]}>
          <Input maxLength={160} />
        </Form.Item>
        <Form.Item name="description" label="服务说明">
          <Input.TextArea rows={4} maxLength={4000} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
