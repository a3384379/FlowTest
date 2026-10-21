# PR145 复审补修

[PR #145](https://github.com/a3384379/FlowTest/pull/145) 的4ae14e0复审提出两项P2，本回执记录修复，不改冻结审计问题数量。

1. 发布来源的性能/Runner搜索状态保留在父组件，但弹窗销毁重开后输入框为空。新增当前搜索值传递和受控输入草稿，重开显示实际过滤条件，明确提交搜索时同步去掉首尾空格。
2. 首次风险目录完成后自动写入默认risk参数，可能使在途质量命令被位置key保护误判为过期。按项目跟踪整个命令生命周期（包含刷新和成功处理），在全部在途命令结束后才自动固定默认风险；同时检查Data Router当前key，避免旧渲染的默认选择覆盖已创建或手动选择的新风险。真正的切项目/导航仍使旧命令失效。

五项新增公开行为测试先复现：5失败、26通过。首次补修后来源重开通过，质量命令已正常成功，但三项即时消息可见性断言遇入场动画；改为等待原可见性断言后，进一步复现新风险仍被默认选择覆盖。增加当前路由key检查后，最终两个文件31项通过；另两个文件34项通过，共65项，保留旧跨项目、权限失败、门禁及关联判断断言。格式、lint/类型和构建通过。

专用隔离浏览器分别搜索性能和Runner来源、关闭重开、核对原搜索值并清空恢复目录，通过；最终业务写入0、队列0。首次脚本将一次正常的auth/refresh误计入业务写入，原日志保留；requests记录确认刷新返回200，脚本改为逐路径区分认证刷新和业务请求后继续只读核验，没有创建新判断或执行。

日志：`remediation-pr145-review-before.log`、`remediation-pr145-review-after.log`、`remediation-pr145-review-final.log`、`remediation-pr145-context-final.log`、`remediation-pr145-quality-expanded.log`、`remediation-pr145-context-lint.log`、`remediation-pr145-context-build.log`、`remediation-pr145-browser-search-final.log`，均在本地忽略的output目录。

本次变更只有前端。batch-21中174文件1229项的完整本地结果对应其记录的旧前端树，不冒充本次最终树完整结果；最新PR的完整前端、Compose及正式Required Gate需按最新HEAD重新核验。后端源码未变，1900项完整结果仍对应同一后端树。

此前PR144合并后[Full Regression 39599686011](https://github.com/a3384379/FlowTest/actions/runs/39599686011)已确认完成为success，head精确为a18dcf2c6a184e777ad5ee173e03356d8515ff87；这不替代本PR门禁或正式环境验收。

## 7643fec 的 Compose 失败与补修

正式运行39610593152的Compose作业失败：S28缺少原有可访问覆盖率进度条，S31全局模糊匹配PASS命中了已关闭详情内的隐藏passed文字；64项通过，S21导航首次超时、既有重试后通过，单列为1项flaky。没有调整超时、重试次数或验收阈值。

恢复Coverage Matrix的可访问进度条，数值始终取整份冻结分析，即使定位到单条变更也不改变整体覆盖率。具名测试先1失败/17通过，补修后连同发布页两个文件39项通过。S31保留原PASS可见性断言，改为定位当前判断行的精确PASS，避免隐藏快照中的相似文字。格式、lint/类型、构建通过。

隔离浏览器读取已存在的固定Impact 3e22dcf4-c1ee-47b1-83da-838683a47e3e，进度条为100；读取旧PASS判断ac31fcbd-e215-4c80-a3e2-4609d97f7181，关闭详情后精确定位原判断行PASS并重开同一ID，通过。业务写入0、执行0，没有为替换失败记录而新建判断。日志remediation-pr145-coverage-before.log、remediation-pr145-compose-fix-targeted.log、remediation-pr145-compose-fix-lint.log、remediation-pr145-compose-fix-build.log、remediation-pr145-coverage-pass-browser.log；完整旧作业日志remediation-pr145-764-compose-full.log保留。

最新HEAD的正式门禁仍需重新核验；上述失败不因补修而改记为成功。
