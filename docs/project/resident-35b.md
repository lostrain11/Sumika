# 35B 单模型常驻（2026-10-19）

当前按用户要求，笔记本只保留一个推理模型：MiniCPM-V 4.7 35B-A3B IQ3_XS，端口 `8083`，文本/视觉/OCR 共用。旧 8082（Qwen 文本）与 8083（1B 视觉）进程已停止，对应计划任务已禁用。

## 配置

- 模型：`D:\Models\minicpm-v47\35B-IQ3_XS.gguf`（NVMe SSD）
- mmproj：`D:\Models\minicpm-v47\35B-mmproj-f16.gguf`
- 启动脚本：`D:\Models\minicpm-v47\serve-35b.cmd`
- 计划任务：`Sumika-Llama-MiniCPM35B`，`onstart`，SYSTEM，Highest
- 参数：`-ngl 99 --n-cpu-moe 99 -c 4096 --host 0.0.0.0 --port 8083 --jinja --reasoning off`
- 日志：`D:\Models\minicpm-v47\35b-resident.log`
- 旧任务：`Sumika-Llama-Qwen4B`、`Sumika-Llama-V471B` 已禁用（未删除，可恢复）

## 实测

- SSD 加载约 6–8 秒（HDD 约 30 秒）
- 文本 JSON：约 7–8 秒；短改写约 8–9 秒
- 真实渲染屏幕 OCR：全文字约 51 秒，内容完整；表格 JSON 约 25 秒
- 35B 使用 GPU 约 2.9GB，MoE 专家在 CPU；不是全 GPU
- 8082/8084 不监听；8085 音频服务独立保留

## 操作

```powershell
# 状态
schtasks /query /tn Sumika-Llama-MiniCPM35B /fo LIST
curl http://192.168.31.227:8083/health

# 停止（任务 + 进程）
schtasks /end /tn Sumika-Llama-MiniCPM35B
# 如进程仍在，按 8083 端口确认 PID 后停止

# 启动
schtasks /run /tn Sumika-Llama-MiniCPM35B
```

## 限制

- 单一模型，8082 文本/8083 1B 视觉不再作为回退；服务崩溃时两者都不可用。
- 16GB 内存余量有限，长上下文/大图可能换页。
- 提示词优化仍不由本地模型负责；35B 改写未通过质量门。
- 常驻任务与计划任务属于本机共享服务变更；恢复旧服务需重新启用两个旧任务并停止 35B。
- 真实屏幕测试使用受控本地 HTML，不包含用户私人窗口。
