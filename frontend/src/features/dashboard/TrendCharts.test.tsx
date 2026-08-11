import { render, screen } from '@testing-library/react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ReportTrend } from '../../lib/api'
import { ReportTrendChart } from '../reports/ReportTrendChart'
import { DashboardTrendChart } from './DashboardTrendChart'

const chart = vi.hoisted(() => ({
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
}))
const initChart = vi.hoisted(() => vi.fn(() => chart))

vi.mock('echarts/core', () => ({ init: initChart, use: vi.fn() }))

describe('trend charts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue('FlowTest browser')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders dashboard trend data and releases the chart lifecycle', () => {
    const points = [{ date: '2026-08-12', total: 4, passed: 2, failed: 1, running: 1 }]
    const view = render(<DashboardTrendChart points={points} />)

    expect(screen.getByLabelText('最近七日执行趋势')).toBeVisible()
    expect(initChart).toHaveBeenCalled()
    expect(chart.setOption).toHaveBeenCalledWith(
      expect.objectContaining({
        xAxis: expect.objectContaining({ data: ['08-12'] }),
        series: expect.arrayContaining([expect.objectContaining({ data: [2] })]),
      }),
    )
    act(() => window.dispatchEvent(new Event('resize')))
    expect(chart.resize).toHaveBeenCalled()
    view.unmount()
    expect(chart.dispose).toHaveBeenCalled()
  })

  it('renders report trends and safely handles an absent series', () => {
    const trend: ReportTrend = {
      points: [
        {
          date: '2026-08-12',
          total: 3,
          passed: 1,
          failed: 1,
          cancelled: 1,
          pass_rate: 33.33,
          average_duration_ms: 120,
        },
      ],
      failures: [],
    }
    const view = render(<ReportTrendChart trend={trend} />)

    expect(chart.setOption).toHaveBeenCalledWith(
      expect.objectContaining({
        series: expect.arrayContaining([expect.objectContaining({ name: '取消', data: [1] })]),
      }),
    )
    view.rerender(<ReportTrendChart trend={undefined} />)
    expect(initChart).toHaveBeenCalledTimes(1)
    view.unmount()
    expect(chart.dispose).toHaveBeenCalled()
  })
})
