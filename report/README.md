# D7报告

[report.pdf](build/report.pdf)与本仓库的030—039结果同步。报告使用英文，正文只陈述已完成的实验、结果复核、时序正确的图和子会话支持；没有把未完成的来源排名、评分或基线比较写成结果。

表格由当前results.json、b1-b2-verification.json和COMPLETED.json生成，图来自当前run-039-protected.svg。成员姓名、学号及个人贡献仍需组内确认，当前只署项目组名称。

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
