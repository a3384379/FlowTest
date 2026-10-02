import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use as registerECharts } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'
import { Empty } from 'antd'

import type { ReportTrend } from '../../lib/api'
import { iceChartTheme, iceColors } from '../../theme/ice-theme'
import { useReducedMotion } from '../../theme/use-reduced-motion'

registerECharts([LineChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer])

export function ReportTrendChart({ trend }: { trend: ReportTrend | undefined }) {
  const container = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()

  useEffect(() => {
    if (!container.current || !trend?.points.length || navigator.userAgent.includes('jsdom')) return
    const chart = init(container.current, iceChartTheme, { renderer: 'svg' })
    chart.setOption({
      animation: !reduced,
      tooltip: { trigger: 'axis' },
      legend: { top: 0, data: ['通过', '失败', '取消'] },
      grid: { left: 42, right: 20, top: 38, bottom: 30 },
      xAxis: { type: 'category', data: trend.points.map((point) => point.date.slice(5)) },
      yAxis: { type: 'value', name: '次', minInterval: 1 },
      series: [
        {
          name: '通过',
          type: 'line',
          smooth: true,
          data: trend.points.map((point) => point.passed),
          itemStyle: { color: iceColors.success },
        },
        {
          name: '失败',
          type: 'line',
          smooth: true,
          data: trend.points.map((point) => point.failed),
          itemStyle: { color: iceColors.danger },
        },
        {
          name: '取消',
          type: 'line',
          smooth: true,
          data: trend.points.map((point) => point.cancelled),
          itemStyle: { color: iceColors.warning },
        },
      ],
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [trend, reduced])

  return (
    <div ref={container} className="report-trend-chart" aria-label="最近七日执行趋势">
      {!trend?.points.length && (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未提供趋势数据" />
      )}
    </div>
  )
}
