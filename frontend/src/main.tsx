import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App as AntdApp, ConfigProvider } from 'antd'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import zhCN from 'antd/locale/zh_CN'

import App from './App'
import { useAuthStore } from './features/auth/auth-store'
import { shouldSkipAutomaticQueryRetry } from './lib/api'
import './styles.css'

const router = createBrowserRouter([{ path: '*', element: <App /> }])

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: (failures, error) => failures < 1 && !shouldSkipAutomaticQueryRetry(error),
    },
  },
})

useAuthStore.subscribe((state, previous) => {
  if (state.epoch !== previous.epoch) queryClient.clear()
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#5b5cf0',
          borderRadius: 10,
          colorBgLayout: '#f5f7fb',
          colorText: '#172033',
          colorBorder: '#dce2ec',
        },
      }}
    >
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>
  </StrictMode>,
)
