import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import RequestTargetSummary from './RequestTargetSummary'

it.each([
  [null, '环境地址'],
  ['endpoint-b', '服务 Endpoint'],
])('shows the actual preview target and source', (endpointId, source) => {
  render(
    <RequestTargetSummary
      preview={{
        url: 'http://mock-b/gateway/orders',
        target: { environment_name: 'Mock B', endpoint_id: endpointId },
      }}
    />,
  )
  expect(screen.getByText('Mock B')).toBeVisible()
  expect(screen.getByText('http://mock-b/gateway/orders')).toBeVisible()
  expect(screen.getByText(source!)).toBeVisible()
})
