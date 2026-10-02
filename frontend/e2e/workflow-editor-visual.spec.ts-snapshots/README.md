# Workflow DOM 截图基线

本目录保存三档尺寸 × 九种状态的 27 张真实 DOM 基线。2026-10-02 更新为 v5 冰蓝白工作区，包含节点库、两排 Header、检查器分区、最大化配置、运行轨迹和冻结历史。概念设计图用于人工核对结构、层级与状态表达；这些 PNG 用于守住已经审阅的浏览器呈现，不代表 v5 全部设计验收通过。

## 更新与回归

1. 启动 Compose stack，使用 Playwright 1.62.1 的 Linux Chromium。当前基线在官方 `mcr.microsoft.com/playwright:v1.62.1-noble` 环境生成。
2. 完成一个阶段后运行 `pnpm e2e -- e2e/workflow-editor-visual.spec.ts --update-snapshots=all`。
3. 打开 `output/playwright/workflow-final-matrix/linux/` 中的全部原始截图，与权威 UI 契约及参考图逐项比较，更新差距表。
4. 再运行同一测试，去掉 `--update-snapshots`，确认像素回归实际通过。禁止用更新基线命令的成功代替回归通过。

截图测试同时输出 geometry JSON，记录提交 SHA、前端工作区差异摘要、前端源码摘要、viewport、scenario 和浏览器版本。工作区未提交时，SHA 必须结合差异摘要阅读。测试只采集自身创建的合成验收项目。

原始截图不遮罩。像素比较仅遮罩合成项目时间戳、执行 ID、执行时间及节点响应耗时；节点名称、成功/失败状态、按钮和布局保持可比较。字体、节点尺寸和视口稳定后才采集截图。默认、专注、运行与历史检查点通过真实“适应画布”操作取景，产品不会因普通编辑自动取景。

像素差异比例上限为 0.003；另有独立几何断言守住画布高度、列表抽屉宽度、画布占比、工具栏高度、两排 Header 不重叠、最大化请求表单宽度与页面无横向溢出。macOS 可采集原始截图，但相对 Linux 基线的像素检查标记为 NOT RUN。

本次在官方 Playwright Linux arm64 镜像中，使用构建后的真实前端、当前主干的 API/Worker，以及本任务独立 Compose 项目的 PostgreSQL、Redis、MinIO 和 mock-target 生成基线。API/Worker/浏览器使用临时 BuildKit 进程启动，不中断用户已有实例；这项本地验证不代替 GitHub 的完整 Compose 验收。全部 27 张截图已复核；普通模式的像素检查结果见 v5 实施记录。

本轮修复及验收边界见 [审计整改记录](../../../docs/workflow-editor-codeplan/audit-20260913-resolution.md)。

v5 的当前交付范围与剩余验收见 [实施记录](../../../docs/design/ui-v5/implementation.md)。
