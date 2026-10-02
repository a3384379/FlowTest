import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App as AntdApp } from 'antd'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import IceThemeProvider from './theme/IceThemeProvider'
import { applyIceAppearance } from './theme/ice-theme'

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

applyIceAppearance(document.documentElement)

useAuthStore.subscribe((state, previous) => {
  if (state.epoch !== previous.epoch) queryClient.clear()
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <IceThemeProvider>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </AntdApp>
    </IceThemeProvider>
  </StrictMode>,
)
