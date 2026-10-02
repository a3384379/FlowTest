import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use as registerECharts } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'
import { Empty } from 'antd'

import type { DashboardTrendPoint } from '../../lib/api'
import { iceChartTheme } from '../../theme/ice-theme'
import { useReducedMotion } from '../../theme/use-reduced-motion'

registerECharts([LineChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer])

export function DashboardTrendChart({ points }: { points: DashboardTrendPoint[] }) {
  const container = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()

  useEffect(() => {
    if (!container.current || !points.length || navigator.userAgent.includes('jsdom')) return
    const chart = init(container.current, iceChartTheme, { renderer: 'svg' })
    chart.setOption({
      animation: !reduced,
      tooltip: { trigger: 'axis' },
      legend: { top: 0, data: ['通过', '失败', '运行中'] },
      grid: { left: 40, right: 20, top: 38, bottom: 28 },
      xAxis: { type: 'category', data: points.map((point) => point.date.slice(5)) },
      yAxis: { type: 'value', name: '次', minInterval: 1 },
      series: [
        { name: '通过', type: 'line', smooth: true, data: points.map((point) => point.passed) },
        { name: '失败', type: 'line', smooth: true, data: points.map((point) => point.failed) },
        { name: '运行中', type: 'line', smooth: true, data: points.map((point) => point.running) },
      ],
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [points, reduced])

  return (
    <div ref={container} className="dashboard-trend-chart" aria-label="最近七日执行趋势">
      {!points.length && (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未提供趋势数据" />
      )}
    </div>
  )
}
