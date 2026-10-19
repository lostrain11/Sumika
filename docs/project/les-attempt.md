# LES + 定制 llama.cpp-omni + 特殊量化尝试（P6-8）

状态：**partial / 运行时已跑通，未替换常驻 35B**。本任务验证 LES 在笔记本（GTX 1060 6GB / 16GB RAM / i7-7700HQ）上的可行性、构建路径、内存与速度，不把 iPad M4 的 3GB / 17.39 token/s 当作本机结论。

## 结论

- **资产阻塞已解除**：仓库自带 `tools/moe/experts.py` 与 `strip_experts.py`，不需要等公开 expert-major manifest。已从 `35B-IQ3_XS.gguf` 生成并**逐字节校验** 120 个专家张量 / 40 层 / 13,086,228,480 字节。
- **Windows 可构建**：MSVC 19.44 + CUDA 12.9.86 + sm61，CPU 与 CUDA 版 `llama-cli` / `llama-mtmd-cli` 均编译成功。源码原本只有 POSIX `preadv`/`iovec`，已加 Windows 实现。
- **1060 不能照搬 iPad 的直写路径**：CUDA 设备显存不是 host-addressable，专家槽必须放 CPU（`--n-cpu-moe 99`），GPU 只算注意力/稠密部分；iPad 的“preadv 直接写 GPU 可见内存”在这台机器上不可用。
- **实测可用**：CUDA + CPU 专家槽 + LES，短文本 8.5 prompt / 7.1 token/s，真实 1280×720 图 OCR 能正确读出标题、卡片、表格三行与状态，但输出格式偏冗长、200 token 时 JSON 被截断。
- **不替换常驻 35B**：页缓存热时普通 mmap + `--n-cpu-moe 99` 的常驻 35B OCR 为 16.2 prompt / 8.0 token/s、51.3 秒完成且表格完整；LES 的主要收益是**内存占用下降**，不是速度超过常驻。加 JSON schema 后 LES 的结构化 OCR 已能输出完整三行 JSON（61.96 秒 vs 常驻 56.88 秒），但自由格式仍偏冗长、速度仍略慢。
- **stripped GGUF 已可用**：`strip_experts.py` 产出 1.30GB 的 stripped 模型；补上非 Metal 后端的 CPU fallback 后，CUDA + CPU 专家槽 + `--no-mmap` 可正常加载，短文本 8.7 prompt / 7.0 token/s，图像问答正常。磁盘从 25.68GB 降到 13.49GB（省 12.19GB）。
- **容量结论**：LES 释放的是 RAM（约 3GB 工作集 vs 13.5GB 权重文件），stripped 又释放了磁盘；但 6GB 显存和 CPU 活跃参数仍是下一层瓶颈；35B-A3B 仍是这台机器的甜点，更大模型要先算显存/带宽，不能只靠 LES。

## 1. 资产

- 模型：`D:\Models\minicpm-v47\35B-IQ3_XS.gguf`（13.49GB，qwen35moe，40 层，256 专家，top-8，IQ3_S/IQ3_XXS 混合）
- stripped 模型：`D:\Models\minicpm-v47\35B-IQ3_XS-stripped.gguf`（1.30GB，仅 613 个非专家张量；专家由 manifest 合成）
- mmproj：`D:\Models\minicpm-v47\35B-mmproj-f16.gguf`
- 专家目录：`D:\Models\minicpm-v47\les-experts\`
  - `manifest.json`：schema 1，`experts_kind=omni_moe_gguf`，`layout=layer_major_expert`
  - `layer_000.bin` … `layer_039.bin`，合计 12.19 GiB
- 校验：`python tools/moe/experts.py verify --model ... --experts ...` 输出 `verified 120 tensors (metadata and bytes)`，耗时 51.7 秒。
- 工具 bug：上游 `verify` 把文件句柄写回字典导致 `TypeError`；本地 fork 已修正变量遮蔽（`experts` → `handle`），并已回传笔记本。

## 2. 构建

本机桌面：AMD Ryzen 5 5600X / 无 NVIDIA GPU；构建不需要 GPU，运行在笔记本。

工具链：

- Visual Studio 2022 Build Tools：`D:\Tools\VisualStudioBuildTools`（MSVC 14.44）
- 便携 CMake 4.4.4 / Ninja 1.13（pip 安装）
- CUDA 12.9.1：官方 installer 解包为便携目录 `D:\Caches\cuda\toolkit`，不安装进系统
- 构建参数：`-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=61 -DCMAKE_CUDA_FLAGS="-allow-unsupported-compiler -Wno-deprecated-gpu-targets"`

本地 fork 的 Windows 补丁（`D:\Caches\llama.cpp-omni`，未入项目 Git）：

1. `src/llama-moe-slot.cpp`：为 MSVC 补 `struct iovec` 与 `ssize_t`；`NOMINMAX` + `windows.h`。
2. `src/llama-moe-slot.cpp`：`readv_span` 的 Windows 分支改为 `ReadFile` + `OVERLAPPED` 定位读，按 iovec 直接散写，去掉 `_lseeki64` + 全局锁。A/B：同一文本任务从 5.4 提升到 7.1 token/s。
3. `common/arg.cpp`：把 `LLAMA_EXAMPLE_MTMD` 加入 `--reasoning`、`--chat-template-kwargs`、`--chat-template-file` 的可用示例，便于多模态关闭 thinking / 指定模板。
4. 保留 `tools/moe/experts.py` 的 verify 修复。
5. `src/llama-model.cpp`：`create_expert_tensor_from_manifest` 在 CUDA/CPU 没有 alloc-only buft 时，若 LES 开启则回退到 CPU buffer，并要求 `--no-mmap`（否则拒绝并给出明确错误）。这是 stripped 模型能在 CUDA + CPU 专家槽下运行的关键补丁。

构建产物：

- CPU：`D:\Caches\llama.cpp-omni\build-cpu\bin\`
- CUDA：`D:\Caches\llama.cpp-omni\build-cuda\bin\`
- 笔记本运行目录：`D:\Caches\les-cpu\`、`D:\Caches\les-cuda\`（含 cudart/cublas/cublasLt/nvJitLink DLL；本轮清理已删除，需要时从 build-cpu/build-cuda 重新复制）

## 3. 运行配置

```powershell
# CUDA + CPU 专家槽
llama-cli.exe -m 35B-IQ3_XS.gguf `
  --moe-experts D:\Models\minicpm-v47\les-experts `
  --moe-slot-bank 256 -ngl 99 --n-cpu-moe 99 `
  -c 512 -t 4 -n 16 --temp 0 --reasoning off --no-mmap -st

# decode 窗口 / 预读（环境变量）
$env:LLAMA_MOE_DECODE_WINDOW = "32"   # 每层 32 个缓存槽，40 层约 1650 MiB
$env:LLAMA_MOE_LOOKAHEAD_PREFETCH = "8"
```

关键日志：

- `pack=on 40/40 bank=256 shared=on experts=256 preadv=on`：专家槽初始化成功。
- `decode-cache: on cache=32 + prefetch=0 slots/layer × 40 层 = 1280 slots (1650 MiB)`。
- `pread=... io=...`：定位读吞吐；新实现常见 2.5–4.1 GiB/s。
- `lookahead-prefetch: armed=... hits=0`：统计值可疑；`usedpf` 会增长，说明预读槽确实被使用，但 `hits` 计数未覆盖窗口模式，待修。

## 4. 实测

短文本（英文 “Introduce yourself in one sentence.”，16 token）：

| 场景 | prompt | generation | 总耗时 | 备注 |
|---|---:|---:|---:|---|
| CPU-only，window 32，prefetch 8 | 4.8 t/s | 4.0 t/s | 12.2s | 无 GPU |
| CUDA + CPU 专家，旧 Windows I/O | 6.1 t/s | 5.4 t/s | 11.7s | seek+read 全局锁 |
| CUDA + CPU 专家，定位读 | **8.5 t/s** | **7.1 t/s** | **8.9s** | 新实现 |
| CUDA + CPU 专家，定位读，stripped GGUF | **8.7 t/s** | **7.0 t/s** | **8.3s** | 1.30GB base，热缓存；与完整 GGUF 基本持平 |

stripped 模型图像问答（同一张 Edge 渲染图，32 token）：50.5 秒完成，正确描述“任务面板、三个卡片、表格、状态栏”，说明 stripped base + manifest 合成专家 + mmproj 的视觉路径可用。

真实 1280×720 受控 UI 图 OCR（同一张图、同一 prompt）：

| 场景 | prompt | generation | 总耗时 | 结果 |
|---|---:|---:|---:|---|
| LES CUDA，200 token，no-think 模板 | — | — | 72.7s | 标题/侧栏/卡片/表格三行/状态均正确；随后输出 JSON，200 token 时第二行被截断 |
| 常驻 35B（8083），154 token | 16.2 t/s | 8.0 t/s | 51.3s | 完整 Markdown 表格，三行齐全 |
| LES CUDA，220 token，Edge 渲染图 | — | — | 134.3s | 文字全对；JSON 到第二行截断 |
| 常驻 35B，220 token，Edge 渲染图 | 14.4 t/s | 7.1 t/s | 67.3s | 完整文字 + 三行 JSON 数组 |
| LES CUDA + JSON schema，300 token 上限 | — | — | 61.96s | 完整三行 JSON，字段/负责人/日期全对 |
| 常驻 35B + JSON schema，300 token 上限 | 11.4 t/s | 6.4 t/s | 56.88s | 72 token 完整三行 JSON |
| 常驻 35B，短文本（冷页缓存） | 1.1 t/s | 1.2 t/s | 32.4s | 仅作冷缓存参考 |

结论：LES 在真实图像 prefill 上受 SSD 读取量限制（每个 63-token 图像 ubatch 约 4.5GB 专家读取），OCR 总耗时高于页缓存热的常驻 35B；短文本生成则因定位读与 decode 窗口明显改善。

中文改写约束对比（原文含“明天下午 3 点”“一楼会议室”“35B”“50 元以内”）：

- LES：16.45s，prompt 11.1 / generation 5.4 token/s；输出“明天下午 3 点，一楼会议室评审 35B 单模型常驻方案，预算 50 元以内。”，时间、地点、型号、金额均保留，但接近逐字复述，没有真正缩短。
- 常驻 35B：32.55s（冷页缓存），prompt 2.76 / generation 3.18 token/s；输出同样保留全部约束，也接近逐字复述。
- 两者都没通过“更简洁”的质量目标；LES 在这一轮冷缓存下总耗时更快，但不能据此推断热缓存下也更快。

加载：常驻日志 `model loaded` 在 5.16 秒；LES 总耗时 8.9 秒减去约 1.9 秒 prompt eval 与 2.3 秒 decode，估计加载约 4–5 秒（未单独打点）。

## 5. 内存 / 容量

采样（LES OCR 与常驻同时运行）：

- LES 进程：max working set **3159 MiB**（完整 GGUF）/ **2984 MiB**（stripped），max private 约 6920 MiB
- GPU：min 2874 MiB，max **5796 / 5844 MiB**（与常驻同开，6144 MiB 总量）
- 常驻 35B 空闲：working set 606 MiB，private 4.72 GiB，GPU **2874 MiB**

即 LES 自身 GPU 约 2.9GB；替换常驻后可剩约 3.1GB 显存。LES 的 RAM 工作集约 3GB，远低于 13.5GB 权重文件。

容量公式与更大模型分析见 [LES 运行时复用与容量](les-runtime-reuse.md)。简要结论：

- RAM 不再是主要限制；
- 6GB 显存是硬限制（dense 部分 + mmproj + KV + CUDA 上下文）；
- 磁盘：完整 GGUF + sidecar = 27,569,917,888 字节（25.68 GiB）；stripped + sidecar = 14,483,680,512 字节（13.49 GiB），**省 12.19 GiB**；
- stripped 模型在 CUDA/CPU 后端可用，但必须 `--no-mmap`；这是 CPU fallback 的明确边界；
- CPU 活跃参数约 3B 时文本 7.1 token/s；更大 active 参数会线性变慢。

## 6. 限制

- 不是 iPad 的 17.39 token/s 路径；不要把移动端数据外推到 1060。
- 图像 prefill 的专家读取量很大，OCR 速度受 SSD 带宽和页缓存影响明显。
- `--moe-experts` 运行时目前只接受 `qwen35moe`；换模型需要适配层。
- 预读 `hits=0` 统计未修；预读是否真正命中要结合 `usedpf` 看。
- 完整 GGUF 与 sidecar 同时占磁盘；stripped 模型可在 CUDA/CPU 后端使用，但必须 `--no-mmap`；缺省会加载失败，当前只显示通用的 `Failed to load the model`。
- 自由格式输出仍偏冗长；JSON schema 约束后 LES 能输出完整三行 JSON（61.96 秒），但比常驻（56.88 秒）慢约 9%。
- 未替换常驻 8083，未改 Sumika 产品设置，未提交源码或推送。
- OCR 对照图是受控 Edge 1280×720 渲染（`ocr-html.png`），没有读取用户真实桌面或私人窗口；真实桌面采集仍受非交互 SSH 会话限制。

## 7. 下一步

1. 修预读命中统计与窗口模式计数，确认 `hits` 是否真实为 0；若预测质量差，调 depth/层选择。
2. JSON schema 质量门已通过（三行全对，61.96 秒）；下一步用 2–3 张不同布局的图复验，并检查自由格式/多图/长上下文。
3. stripped 已打通；下一步用容量公式挑选 50–60B 级、active 约 3B 的 MoE，先算显存/磁盘/带宽再下载。
4. 若要继续 GPU 化：设计 pinned staging + `cudaMemcpyAsync` + 事件同步的 GPU slot bank；先单层原型，再全模型；这是可复用的通用层，但工作量和风险明显高于当前 CPU 专家槽。
5. 更大模型：优先找“总参数更大、active 仍约 3B、dense 维度和层数不显著增加”的 MoE；先算容量再下载，不盲目上 70B。

## 8. 最新模型与 DSpark 评估（2026-10-19）

按 Hugging Face `lastModified` 检索：

- OpenBMB 最新仍是 MiniCPM-V 4.7 系列（10-15/10-16），包括 35B-A3B、1B、GPTQ/AWQ/FP8 和 **DSpark draft**；没有更大的 MiniCPM-V 版本。
- Qwen 最新是 Qwen3.8 系列（2026-08）：27B、2.4T-A95B、Flash-Next。Flash-Next 是 `qwen4_exp`（48 层、512 专家、top-10），当前 LES 运行时未接该架构，体量也远超本机。
- 唯一更大的同架构（`qwen3_5_moe`）候选是 **Qwen3.5-122B-A10B**（2026-04）：48 层、256 专家、top-8、hidden 3072、moe_ff 1024。按 35B 缩放，IQ3 专家 sidecar 约 44GiB、dense 约 3.5–5GB、active 10B；6GB 显存只能勉强文本、视觉基本不可行，CPU 预计 1.5–2 token/s。最小 GGUF（IQ2_XXS）36.6GB，仍需转换/提取和大量磁盘，未下载。

DSpark（2026-10-16 最新发布）实测：

- draft 389M 参数，Q8_0 约 424MB，与当前 35B 配对；`-md ... --spec-type draft-dspark` 可正常加载并输出正确文本。本轮清理已删除 draft 文件，需要时重新下载。
- `n_max=15`、window 32：generation **1.9 token/s**。验证批宽 16 被当作 prefill，每步读约 2.2GB 专家，窗口不生效。
- `n_max=7`、window 64 / rows 8：generation **2.9 token/s**。窗口开始命中（`hit` 增长），但每步 8 token 的目标验证仍重。
- 非投机 LES 是 **7.0 token/s**。结论：DSpark 在“CPU 专家槽 + 6GB 显存”上是负收益，不启用；不是模型本身的问题，而是验证批宽和 CPU 专家读取的代价。

**模型结论**：没有比 35B-A3B 更适合这台机器的“更新且更大”候选。要么接受 122B-A10B 的约 2 token/s 文本级速度，要么等新的 3B-active MoE；在当前硬件上继续用 35B-A3B 是合理选择。

## 9. LFM2.5-24B-A2B 对比（2026-10-19）

- **LFM2.5-24B-A2B 是 LFM2.5 家族最大、也是最后一款**：24B total / 2B active，text-only reasoning，40 层、64 专家、top-4、131k 上下文，Q4_K_M 约 14.5GB。没有更大的 LFM2.5；LFM2.5-8B-A1B 更新但更小，LFM2.5-VL-3B 是视觉小模型；更早的 LFM1 40B MoE 不是这一代。
- **LES 不能直接测 LFM**：LFM GGUF 的 `arch=lfm2moe`，而 `--moe-experts` 运行时只接受 `qwen35moe`。要 LES 化需要给 `src/models/lfm2moe.cpp` 写专家虚拟化/slot 适配；LFM 本身比 35B 小，普通 llama.cpp 已能跑，投入产出比低，未做。
- 普通 llama.cpp 实测（测试时复制到 D: SSD，测试后已删除副本，原始保留在 F:\GGUF；`-ngl 99 --n-cpu-moe 99 --reasoning-budget 0 --no-warmup`）：
  - 短英文：prompt 13.5 / generation 5.8 token/s，总 10.1 秒；v4.7 LES 是 8.5 / 7.1、8.9 秒。
  - 中文改写：LFM 13.1 秒，generation 12.8 token/s，输出“明天下午3点，一楼会议室评审35B单模型常驻方案，预算50元以内。”，时间/地点/型号/金额都保留，但接近逐字；v4.7 LES 16.45 秒、5.4 token/s；常驻 35B 32.55 秒。

**选择建议**：需要 OCR/视觉/多模态 → v4.7；纯文本/角色/Agent 且追求速度 → LFM2.5-24B-A2B。两者同时常驻会接近 6GB 显存上限，需实测，不建议默认双开。

## 10. 证据

- 资产/校验：`D:\Models\minicpm-v47\les-experts\manifest.json`；verify 日志 `D:\Models\minicpm-v47\les-verify.log`
- 构建日志：`D:\Caches\llama.cpp-omni\build-cpu.log`、`build-cuda.log`、`build-cpu-io2.log`、`build-cuda-io2.log`
- 运行日志：`D:\Models\minicpm-v47\les-cuda-io3.log`（7.1 t/s）、`les-cuda-ocr3.log`、`les-cuda-ocr-nothink.log`、`les-html-ocr.log`、`les-json-ocr2.log`（schema 质量门）、`les-rewrite.log`、`les-cpu-8tok.log`、`les-stripped-text2.log`、`les-stripped-vision.log`
- stripped：`D:\Models\minicpm-v47\35B-IQ3_XS-stripped.gguf`（1,397,452,032 字节）；生成日志 `D:\Models\minicpm-v47\strip-experts.log`
- OCR 对照图：`.sumika-next/les/ocr-html.png`（Edge 渲染）与 `ocr-fixture-1280x720.png`（PIL 合成）；测试图/提示词/脚本在 `D:\Models\minicpm-v47\les-test\`，工作区副本 `.sumika-next/les/`
- 常驻基线：`bench_resident.py` 输出（文本 32.4s；OCR 51.3s，8.0 token/s）
