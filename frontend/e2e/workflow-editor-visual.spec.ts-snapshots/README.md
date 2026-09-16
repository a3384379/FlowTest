# Workflow DOM 截图基线

本目录保存三档尺寸 × 九种状态的 27 张真实 DOM 基线。概念设计图用于人工核对结构、层级与状态表达；这些 PNG 用于守住已经审阅的浏览器呈现，不代表 V2 全部设计验收通过。

## 更新与回归

1. 启动 Compose stack，使用 Playwright 1.62.1 的 Linux Chromium。当前基线在官方 `mcr.microsoft.com/playwright:v1.62.1-noble` 环境生成。
2. 完成一个阶段后运行 `pnpm e2e -- e2e/workflow-editor-visual.spec.ts --update-snapshots=all`。
3. 打开 `output/playwright/workflow-final-matrix/linux/` 中的全部原始截图，与权威 UI 契约及参考图逐项比较，更新差距表。
4. 再运行同一测试，去掉 `--update-snapshots`，确认像素回归实际通过。禁止用更新基线命令的成功代替回归通过。

截图测试同时输出 geometry JSON，记录提交 SHA、前端工作区差异摘要、前端源码摘要、viewport、scenario 和浏览器版本。工作区未提交时，SHA 必须结合差异摘要阅读。测试只采集自身创建的合成验收项目。

原始截图不遮罩。像素比较仅遮罩合成项目时间戳、执行 ID、执行时间及节点响应耗时；节点名称、成功/失败状态、按钮和布局保持可比较。专注模式检查点通过真实“适应画布”操作取景，产品不会因普通编辑自动取景。

像素差异比例上限为 0.003；另有独立几何断言守住画布高度、列表宽度、画布占比、工具栏高度、Header 不重叠与页面无横向溢出。macOS 可采集原始截图，但相对 Linux 基线的像素检查标记为 NOT RUN。

本轮修复及验收边界见 [审计整改记录](../../../docs/workflow-editor-codeplan/audit-20260913-resolution.md)。
