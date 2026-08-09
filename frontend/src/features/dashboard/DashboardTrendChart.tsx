import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use as registerECharts } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

import type { DashboardTrendPoint } from '../../lib/api'

registerECharts([LineChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer])

export function DashboardTrendChart({ points }: { points: DashboardTrendPoint[] }) {
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!container.current || navigator.userAgent.includes('jsdom')) return
    const chart = init(container.current, undefined, { renderer: 'svg' })
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['通过', '失败', '运行中'] },
      grid: { left: 40, right: 20, top: 38, bottom: 28 },
      xAxis: { type: 'category', data: points.map((point) => point.date.slice(5)) },
      yAxis: { type: 'value', minInterval: 1 },
      series: [
        { name: '通过', type: 'line', smooth: true, data: points.map((point) => point.passed) },
        { name: '失败', type: 'line', smooth: true, data: points.map((point) => point.failed) },
        { name: '运行中', type: 'line', smooth: true, data: points.map((point) => point.running) },
      ],
      color: ['#22a06b', '#dc4446', '#2563eb'],
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [points])

  return <div ref={container} className="dashboard-trend-chart" aria-label="最近七日执行趋势" />
}
