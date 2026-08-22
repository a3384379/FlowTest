import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { useState } from 'react'

import { apiErrorMessage } from '../../lib/api'
import { useAuthStore } from './auth-store'

type PasswordValues = { currentPassword: string; newPassword: string; confirmation: string }

export default function PasswordChangePage() {
  const changePassword = useAuthStore((state) => state.changePassword)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit(values: PasswordValues) {
    setSubmitting(true)
    setError(null)
    try {
      await changePassword(values.currentPassword, values.newPassword)
    } catch (requestError) {
      setError(apiErrorMessage(requestError))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="centered-page">
      <Card className="password-card">
        <Typography.Title level={3}>首次登录，请修改密码</Typography.Title>
        <Typography.Paragraph type="secondary">
          新密码至少 8 位。完成后即可进入 FlowTest 工作台。
        </Typography.Paragraph>
        {error && <Alert type="error" showIcon message={error} className="form-alert" />}
        <Form<PasswordValues> layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item label="当前密码" name="currentPassword" rules={[{ required: true }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            label="新密码"
            name="newPassword"
            rules={[{ required: true, min: 8, message: '新密码至少 8 位' }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            label="确认新密码"
            name="confirmation"
            dependencies={['newPassword']}
            rules={[
              { required: true },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  return value === getFieldValue('newPassword')
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入的密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>
            保存并进入平台
          </Button>
        </Form>
      </Card>
    </main>
  )
}
