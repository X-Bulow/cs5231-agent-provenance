# D7正式实验入口

当前结果集固定为030—039，正常／文档注入各五次。

- d7/protocol.json：唯一有效运行配置；input-lock.json核对当前输入。
- d7/controlled_collect.py：四段／600秒策略，当前要求显式传入模型。
- v2-d7/capture/：不可改写的采集时协议、启动前记录及访问规则，只供核实当时执行事实。
- v2-d7/：逐次环境、检查、结果、人工复核、原始编辑重放和测试日志。
- manifest.json/csv及review-notes.json：当前十次清单。
- delegated-sessions.json：039原生子会话关联与校验。
- v2_batch.py：verify仅校验输入；run明确启动一个新编号并拒绝覆盖。
- build_manifest.py、v2_results.py、v2_verify.py：核对当前证据、汇总结果与验证图。

配置和采集路径以[README_new.md](../README_new.md)为准。原始元数据可能保留采集当时的来源路径或检查上下文，它们不提供其他配置的启动入口。模型输出是待核对的实验记录，不能据其自称完成判定合法任务成功。

## C1、C2 离线分析

执行 `python3 -B experiments/c1_c2.py` 生成 [c1-c2/](v2-d7/c1-c2/) 的调查、前后追踪、逐来源证据和八个编辑起点的排序。输入不增加模型运行；已知注入路径仅用于排序后的验收查找。四次违规运行共八次编辑，六次合法运行未判违规；来源文档均并列第一，没有唯一归因。详见 [完整方法](../docs/c1-c2-analysis.md)。

## C3 离线稀有度

执行 `python3 -B experiments/c3_results.py` 或只读 `--check`，输出位于 [c3/](v2-d7/c3/)。五正常运行按完整运行是否出现某特征计数，另做五折四参考检查。规则及正常高分反例见 [分析说明](../docs/c3-analysis.md)。本步骤不融合 C1/C2；C4 同输入比较另见下节。

## C4 同输入图／日志比较

`python3 -B experiments/c4_results.py` 生成 [c4/](v2-d7/c4/)，加 `--check` 只读复现。日志基线不读图，共用已声明的 Shell／内容规则；双方定位、来源名次和前序调用集合相同。详见 [指标口径与结果](../docs/c4-evaluation.md)。未进行人工耗时研究。
