# D7解析与构图验收

当前仅保留030—039十份有效父会话、039的一份原生子会话图及15张SVG。当前验证只读取D7正式记录。

解析器不再把未来用户续行提前合进初始任务。首条消息为O:prompt，后续消息记录真实到达位置，只连接其到达后的第一条助手响应。例如030的第二条消息在T14之前到达，不能成为此前响应或调用的祖先。原始输入和工具返回仍保存，路径归一不会改变失败状态。

039的父C3是task调用，原生子会话另行导出并核对标识、工作目录、时间和哈希。父图以delegated-session推断规则汇总任务边界上的文件变化，写入边保留子调用11和12；子图保留内部两个测试版本。子原生导出没有独立事件流，因此不声称拥有父会话同等级的双记录交叉核对。

针对十次正式记录，核查从老师初始文件及场景差异恢复内容，再按原始write内容、edit替换文本重放，039在父task位置插入子操作。完成后才与最终check.json比较。十次全部一致，原始文件也与采集结束时保存的逐文件校验表一致。

正式记录共20个最终变化文件：8个最后版本哈希在最终检查前已知，12个由最终检查回填。后12个不称为图独立预测；另行的原始内容重放提供独立核对。子图最终变化使用子原始内容重放计算。

当前测试只覆盖D7会话、用户到达顺序、子会话、受保护与合法编辑、invalid工具、清单缺失／陈旧证据、Shell分析及SVG。测试数量和通过结果以experiments/v2-d7/provenance-tests.txt为准。机器可读验收为b1-b2-verification.json。

在作业总目录先source .experiment-env/activate.sh，再执行：

```bash
python3 -B cs5231-agent-provenance/experiments/v2_batch.py verify
python3 -B cs5231-agent-provenance/experiments/build_manifest.py --check
python3 -B cs5231-agent-provenance/experiments/v2_verify.py
python3 -B -m unittest discover -s cs5231-agent-provenance/provenance -v
```

这些检查不启动模型。图中命令推断和子会话汇总均明确标记，不冒充系统调用或因果证明。未进行Part C、提交或推送。
