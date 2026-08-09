import { ApiOutlined, LockOutlined, MailOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { useState } from 'react'

import { apiErrorMessage } from '../../lib/api'
import { useAuthStore } from './auth-store'

type LoginValues = { email: string; password: string }

export default function LoginPage() {
  const login = useAuthStore((state) => state.login)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit(values: LoginValues) {
    setSubmitting(true)
    setError(null)
    try {
      await login(values)
    } catch (requestError) {
      setError(apiErrorMessage(requestError))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-hero">
        <div className="login-product-mark">
          <ApiOutlined />
          <span>FlowTest</span>
        </div>
        <Typography.Title>让接口测试像搭积木一样简单</Typography.Title>
        <Typography.Paragraph>
          可视化管理接口、环境与自动化流程，快速定位每一次请求和断言结果。
        </Typography.Paragraph>
      </section>
      <Card className="login-card" variant="borderless">
        <Typography.Title level={3}>登录账号</Typography.Title>
        <Typography.Paragraph type="secondary">请使用管理员分配的内部账号</Typography.Paragraph>
        {error && <Alert type="error" showIcon message={error} className="form-alert" />}
        <Form<LoginValues> layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item
            label="邮箱"
            name="email"
            rules={[{ required: true, type: 'email', message: '请输入有效邮箱' }]}
          >
            <Input
              autoComplete="username"
              prefix={<MailOutlined />}
              size="large"
              placeholder="name@example.com"
            />
          </Form.Item>
          <Form.Item
            label="密码"
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              autoComplete="current-password"
              prefix={<LockOutlined />}
              size="large"
              placeholder="请输入密码"
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={submitting}>
            登录
          </Button>
        </Form>
      </Card>
    </main>
  )
}
