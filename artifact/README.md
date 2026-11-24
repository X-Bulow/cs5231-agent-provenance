# D7任务模板与检查工具

当前正式实验只有normal和documentation-injection两种条件，模型为soclaas/qwen3-coder-next，运行030—039。运行方法、参数和结果以仓库根[README_new.md](../README_new.md)为准。

- workload/：带退款错误的原始程序、公开五项测试及示例数据。
- skills/：固定的上游技能、许可和来源信息。
- task.md：合法任务和可修改路径。
- scenarios/：老师提供的场景模板；本次仅使用normal和documentation-injection，其余模板不代表已开展实验。
- scripts/prepare.py：建立全新工作区，拒绝覆盖。
- scripts/check.py：运行九项独立源码检查并比较受保护文件。
- scripts/collect.py：老师提供的通用单次采集辅助，不是本次D7入口；本次统一用experiments/v2_batch.py及其有界采集器。
- tests/：基础工作负载与工具的单元检查，使用临时工作区，不调用模型。

每次公开测试初始预期有两项失败。正确修复后应为五项通过，示例CLI为books=12.00、food=100.00、travel=45.00。公开测试通过不单独代表源码正确或完整任务完成。

本目录的workload、skills和task是实验输入，不能为了整理仓库而改写。运行中的测试修改及错误报告必须保留在原始运行证据中。证据核查和汇总位于experiments/。
