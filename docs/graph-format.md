# D7图数据格式

图从原生会话生成，当前只处理030—039及039子会话。schema_version为1或2；出现多条用户消息或委派汇总边时用版本2。

## 节点

- O:prompt保存首条用户消息，kind=prompt、trust=user。
- O:user:2等保存后续消息。before_turn表示消息到达后第一条助手响应的编号；READ边只连接该轮，不能提前连接T1。末尾没有后续响应的消息只保留节点。
- T:n是一条助手响应，保留消息标识、调用编号、文字与时间。
- C:k是一次原生工具调用，保留call_id、状态、输入、退出码与时间。
- O:result:k保存工具返回。失败文本和invalid工具返回不会被改成成功文件访问。
- O:file:path@vN表示文件版本。v0来自初始文件，后续版本来自写入；trust区分技能、初始工作区和产生的内容。

## 关系与证据

EXEC连接助手响应与其调用，NEXT连接连续响应，READ表示读取，WRITE表示产生返回或新版本。basis=recorded表示直接记录；basis=inferred表示推断，必须附rule。

当前推断规则包括command-text、known-script、tool-output、hash-diff和delegated-session。Shell关系来自命令与输出分析，不冒充系统调用观测。

039父图的delegated-session边按task边界汇总已核对的子会话操作，保留child_session_id及child_call_evidence；evidence仍指父task编号。子图另保留内部两次测试编辑，父图不伪造直接edit调用。

原始输入和返回保留在原生文件与解析内存的raw_input、raw_output中；图展示只清理已知工作区前缀。完整写入内容计算的哈希、原始编辑重放得到的哈希、最终check.json回填的哈希在验收中分别说明。

所有边须符合节点类型、证据编号和到达顺序，图不能有环。图的可达关系不单独证明注入造成了后续动作。复核入口为experiments/v2_verify.py。
