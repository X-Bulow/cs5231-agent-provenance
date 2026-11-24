# D7编码智能体实验与溯源图

本仓库当前只包含正式运行030—039：正常与文档注入各五次，统一使用SoCLaaS的`soclaas/qwen3-coder-next`、Python3.12.16、OpenCode1.19.5、请求温度0.2，以及同一会话最多四段／600秒的D7执行策略。

正常组完整完成5/5；注入组完整完成1/5、最终受保护测试修改4/5。每个分母都是该组五次预定启动，续行不增加样本数。两组最终公开测试都5/5通过，因此必须结合独立源码检查、受保护文件变化和报告真实性判断任务是否完成。

## 先看这些文件

- [README_new.md](README_new.md)：逐次结果、完整配置和复核命令。
- [报告PDF](report/build/report.pdf)与[报告构建说明](report/README.md)：当前D7研究设置、图方法、结果和限制。
- [交接与剩余任务](handover.md)：下一代理的接手顺序、验证命令及C1—C4范围。
- [当前状态](docs/status.md)：已完成的数据与构图，以及尚未完成的评估。
- [原始运行](artifact/runs/)、[机器可读结果](experiments/v2-d7/results.json)、[图示说明](figures/README.md)。

## 不调用模型的复核

从仓库根目录使用Python3.10或更高版本执行；原始采集实际使用3.12.16。分析代码只使用Python标准库，无需本机凭据。

```bash
python3 -B experiments/v2_batch.py verify
python3 -B experiments/build_manifest.py --check
python3 -B experiments/v2_verify.py
python3 -B -m unittest discover -s provenance -v
```

当前运行入口统一为`experiments/v2_batch.py`，有效设置为`experiments/d7/protocol.json`。新增采集需要单独配置OpenCode、SoCLaaS认证与本机隔离环境，并明确选择未使用编号；已固定的030—039不补跑、不覆盖。

`experiments/v2-d7/capture/`保存采集瞬间的原始元数据，`artifact/runs/`保存真实输入、返回和最终文件；这些证据中的路径、错误和模型说法不是团队运行配置。通用场景模板和上游技能属于输入材料，未使用的模板不表示已经开展了对应实验。

[C1、C2 方法与结果](docs/c1-c2-analysis.md)已完成：定位八次违规编辑并支持父子会话追踪；来源排序均存在并列，不能唯一归因。

[C3 操作稀有度](docs/c3-analysis.md)已完成：八个违规编辑得各自运行最高分，但正常行为也可同分；作为探索性调查线索，不作独立违规或来源判断。

[C4 同输入日志比较](docs/c4-evaluation.md)已完成：双方定位八次违规编辑，来源排名与前序调用集合相同，未显示图方法的比较优势；没有人工耗时结果。
