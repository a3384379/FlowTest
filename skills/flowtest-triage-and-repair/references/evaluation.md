# 独立评测与证据边界

本 Skill 可整目录复制安装；评测不需要 FlowTest 源码、数据库或网络连接。
在 Python 3.13 虚拟环境中，从安装目录运行：

```sh
python -m pip install -r evals/requirements.txt
python evals/evaluate.py --check
python evals/evaluate.py
```

依赖安装可以使用组织批准的离线 Wheel。运行评测本身不访问网络。
--check 要求当前标注汇总与 baseline 完全一致且所有硬门禁通过；
缺少硬门禁证据、无效输入或失败门禁均返回非零退出码。

evals 内包含独立 Evaluator、标注、Baseline、Golden Fixture 与 source-map。
source-map 仅说明生成来源，不是运行时外部路径依赖。
这些资产与旗舰 Skill 使用同一份 V6 产品质量口径；复制四份不代表四组独立实验。

此命令仅汇总已提交的人工/测试标注，不执行后端测试，也不是 LLM 实际调用
此 Skill 的成功率、盲测或生产准确率。工具链、权限隔离、幂等写入和人工审核边界
由仓库的真实 MCP/HTTP 集成回归验证；发布记录必须分别列明这两类证据。
如需新增 LLM 效果结论，必须另行记录模型、输入、实际工具轨迹与独立审核标注，
不得把既有 Golden 分数当作该结论。
