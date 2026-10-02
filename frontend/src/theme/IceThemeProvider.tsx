import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useMemo, type ReactNode } from 'react'
import { createIceTheme } from './ice-theme'
import { useReducedMotion } from './use-reduced-motion'

export default function IceThemeProvider({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion()
  const appearance = useMemo(() => createIceTheme(reduced), [reduced])
  return (
    <ConfigProvider locale={zhCN} theme={appearance}>
      {children}
    </ConfigProvider>
  )
}
