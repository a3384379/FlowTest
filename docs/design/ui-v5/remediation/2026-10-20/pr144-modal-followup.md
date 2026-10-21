# PR144 弹窗关闭验收补修

正式运行39583734481在5ba3fe8d40e4d8c82518e320a0c5153fc08ef651结束失败：前端171文件1139通过、2失败；两项新调度测试创建与凭据内容断言通过，但无焦点的Escape未关闭一次性凭据弹窗，关闭后不可见断言失败。其余已选择的后端完整/集成、Compose、Windows及升级检查通过，不等于本HEAD门禁成功。此前回执中“明确关闭按钮”只覆盖了token场景，本次纠正遗漏的两项Webhook场景。

提交2f83d47统一从已可见凭据取得当前弹窗，点击Close后核对凭据不可见；队列场景也从可见计划详情点击Close，并等待URL移除run后再取消队列。未移除业务或可见性断言，未提高超时、添加重试或改变产品。

CI=true具名TestPlansPage全部11项通过（25.93秒），格式、ESLint/TypeScript及生产构建通过，日志remediation-r2-explicit-modal-final.log、remediation-r2-explicit-modal-build.log。旧171文件1141项全量结果仅对应7d7f9a3树；此次测试输入改变后未重跑本地全量，推送后由新HEAD正式门禁验证，不能沿用5ba或旧树结果宣称成功。

本回执补充[第十六批](batch-16.md)和[验证清单](validation.md)，尚未宣称合并、合并后回归或发布验收成功。
