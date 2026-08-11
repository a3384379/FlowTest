import { ApiOutlined, LockOutlined, MailOutlined, SafetyOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Divider, Form, Input, Typography } from 'antd'
import { useEffect, useState } from 'react'

import { apiClient, apiErrorMessage } from '../../lib/api'
import { useAuthStore } from './auth-store'

type LoginValues = { email: string; password: string }
type OIDCStatus = { enabled: boolean; provider: string | null }

export default function LoginPage() {
  const login = useAuthStore((state) => state.login)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [oidcStatus, setOIDCStatus] = useState<OIDCStatus>({ enabled: false, provider: null })

  useEffect(() => {
    let active = true
    void apiClient
      .get<OIDCStatus>('/auth/oidc/status')
      .then((response) => {
        if (active) setOIDCStatus(response.data)
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [])

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
        {oidcStatus.enabled && (
          <>
            <Divider plain>或</Divider>
            <Button href="/api/v1/auth/oidc/login" icon={<SafetyOutlined />} size="large" block>
              使用{oidcStatus.provider ? ` ${oidcStatus.provider} ` : '企业身份'}登录
            </Button>
          </>
        )}
      </Card>
    </main>
  )
}
