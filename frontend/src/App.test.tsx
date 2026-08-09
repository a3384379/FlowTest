import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('App', () => {
  it('renders the initialized dashboard', () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: '工作台' })).toBeInTheDocument()
    expect(screen.getByText('项目工程已初始化，下一步从单接口闭环开始。')).toBeVisible()
    expect(screen.getByText('接口自动化测试平台')).toBeVisible()
  })
})
