import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use as registerECharts } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

import type { ReportTrend } from '../../lib/api'

registerECharts([LineChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer])

export function ReportTrendChart({ trend }: { trend: ReportTrend | undefined }) {
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!container.current || !trend || navigator.userAgent.includes('jsdom')) return
    const chart = init(container.current, undefined, { renderer: 'svg' })
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['通过', '失败', '取消'] },
      grid: { left: 42, right: 20, top: 38, bottom: 30 },
      xAxis: { type: 'category', data: trend.points.map((point) => point.date.slice(5)) },
      yAxis: { type: 'value', minInterval: 1 },
      series: [
        {
          name: '通过',
          type: 'line',
          smooth: true,
          data: trend.points.map((point) => point.passed),
          itemStyle: { color: '#22a06b' },
        },
        {
          name: '失败',
          type: 'line',
          smooth: true,
          data: trend.points.map((point) => point.failed),
          itemStyle: { color: '#dc4446' },
        },
        {
          name: '取消',
          type: 'line',
          smooth: true,
          data: trend.points.map((point) => point.cancelled),
          itemStyle: { color: '#d89614' },
        },
      ],
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [trend])

  return <div ref={container} className="report-trend-chart" aria-label="最近七日执行趋势" />
}
