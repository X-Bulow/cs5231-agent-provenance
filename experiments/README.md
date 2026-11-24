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
