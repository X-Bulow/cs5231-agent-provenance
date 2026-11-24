# D7报告

[report.pdf](build/report.pdf)与本仓库的030—039结果同步。报告使用英文，正文陈述已完成的实验、结果复核、图和子会话支持，以及 C1 调查、C2 内容排序。八次违规编辑均检索到注入文档，但均与其他证据并列，不能唯一归因。C3 稀有度也已完成：违规编辑得到高分，但合法读取和委派也可同分；C4 同输入日志比较也已完成，双方定位、来源排名及前序调用集合相同；人工耗时未测。

表格由当前 results.json、b1-b2-verification.json、C1/C2、C3、C4 的 summary.json 和 COMPLETED.json 生成，图来自当前run-039-protected.svg。成员姓名、学号及个人贡献仍需组内确认，当前只署项目组名称。

## 重新构建

从仓库根目录执行，需Python、Tectonic和支持无界面打印的Chrome／Chromium。Tectonic可通过TECTONIC环境变量或PATH提供，浏览器可通过CHROME指定。首次编译可能需要获取TeX资源，不调用被测模型。

```bash
python3 -B report/build_report.py
```

仅更新LaTeX数据表、不运行浏览器或编译器：

```bash
python3 -B report/build_report.py --tables-only
```

LaTeX源文件在src/，生成表格在src/generated/，报告图在src/figures/，编译PDF在build/report.pdf。编译日志与逐页预览属于本地构建检查，不作为实验运行。
