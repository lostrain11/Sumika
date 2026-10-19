# LES 运行时复用与容量评估

本文记录 P6-8 尝试中可复用的部分、换模型时的适配步骤，以及“能不能上更大端侧模型”的容量算法。实测数据见 [LES 尝试](les-attempt.md)。

## 1. 分层

| 层 | 内容 | 复用性 |
|---|---|---|
| 资产层 | `tools/moe/experts.py` 提取 expert-major sidecar + manifest；`tools/moe/strip_experts.py` 剥离专家 | 对标准 GGUF MoE 的 `blk.N.ffn_{gate,up,down,gate_up}_exps.weight` 通用；需确认专家轴在第 2 维 |
| 清单层 | `schema_version=1`、`experts_kind`、`layout=layer_major_expert`、每张量的 `bytes_per_expert`/`expert_stride` | 与模型无关 |
| 运行时层 | slot bank、decode window、跨层 lookahead 预读、`preadv`/Windows 定位读、LRU | 与模型无关；核心在 `src/llama-moe-slot.cpp` |
| 模型适配层 | `virtualize_expert_tensor`、层内 gate/up/down 打包、decode 窗口 view、每层窗口宽度 | 目前只接 `qwen35moe`；换架构需要改模型图 |
| 观测层 | `[moe-ssd]` 日志、`run_les.py`、`bench_resident.py`、`inspect_gguf.py` | 与模型无关 |

## 2. 换一个 MoE 模型要做什么

1. **检查 GGUF**：`inspect_gguf.py` 看 `arch`、`block_count`、`expert_count`、`expert_used_count`、专家张量形状是否为 `[..., ..., n_expert]`，以及量化类型。
2. **提取资产**：`experts.py extract --model <gguf> --out-dir <dir>`，再 `verify` 做逐字节校验。
3. **确认运行时支持**：`llama-model.cpp` 目前只允许 `qwen35moe` 使用 `--moe-experts`。换架构需要在对应 `src/models/<arch>.cpp` 里接：
   - 创建/虚拟化专家张量（`create_routed_tensor` 的等价逻辑）；
   - 为 gate/up/down（或 gate_up）建立打包视图；
   - 在 MoE 计算前调用 slot 分配、之后写回 slot id；
   - 如果需要 decode 缓存，建立 per-layer 窗口 view。
4. **调参**：`--moe-slot-bank` 至少 ≥ top-k；decode 窗口按显存/内存预算调；预读 depth 先用 4–8。
5. **验证**：先短文本正确性（与普通 mmap 同模型对比），再真实图 OCR，再长上下文/多图/稳定性。
6. **容量检查**：按下面的公式先算，再下载模型。

## 3. 容量公式

记号：

- `F`：GGUF 文件字节数
- `E`：manifest 中所有专家张量的 `exact_byte_length` 之和
- `D = F - E`：非专家（dense/embedding/attention 等）字节数
- `s = Σ bytes_per_expert`：一个专家跨全部 MoE 层的字节数
- `b = s / n_layers`：一层、一个专家的平均字节数（含 gate/up/down）
- `K`：top-k（`expert_used_count`）
- `B`：slot bank 槽位数；`W`：每层 decode 窗口槽位数
- `M`：mmproj 字节数（视觉模型）
- `KV`：KV cache 字节数（随上下文/层数/头数增长）

估算：

```text
RAM  ≈ D(若专家/稠密在 CPU) + B*b + W*n_layers*b + M + KV + 运行时开销
VRAM ≈ D_gpu + M_gpu + KV_gpu + CUDA 上下文
磁盘 ≈ F + E                     # 完整 GGUF + sidecar
磁盘 ≈ D + E                     # stripped 模型 + sidecar（CUDA/CPU 需 --no-mmap）
每 token 读取 ≈ K * s * (1 - 命中率)
I/O 速度上限 ≈ 存储带宽 / 每 token 读取
```

其中 `B*b` 是共享 prefill bank，`W*n_layers*b` 是逐层 decode 窗口；两者都在同一块 base 上，按当前实现相加。

### 35B-A3B 实测代入

- `F=13.49GB`，`E=12.19GiB`，`D≈1.3GB`，`s=48.75MiB`，`b≈1.22MiB`，`K=8`，`n_layers=40`
- `B=256` → 约 0.31GiB；`W=32` → 约 1.61GiB
- 实测 LES OCR：working set 3.16GB，GPU 约 2.9GB；与常驻同开时 GPU 5.80/6.14GB
- 磁盘：13.49 + 12.19 = 25.7GB（完整 GGUF）；stripped 1.30 + 12.19 = 13.49GB，省 12.19GB

## 4. 这台笔记本的容量边界

| 资源 | 现状/余量 | 对更大模型的含义 |
|---|---|---|
| RAM 16GB | LES 工作集约 3.2GB，常驻约 0.6GB WS / 4.7GB private | RAM 已不是主限制；可容纳更大 dense/base |
| VRAM 6GB | LES 约 2.9GB；替换常驻后余约 3.1GB | **硬限制**：更大 dense + mmproj + KV 很快超 6GB |
| 磁盘 D: 83GB | 完整 25.7GB；stripped 13.49GB | stripped 已可用，50–60B 级更从容；70B 级 stripped+sidecar 约 35–45GB，磁盘不再是首要阻塞 |
| NVMe 带宽 | 实测定位读 2.5–4.1GiB/s | 图像 prefill 每 63-token ubatch 约 4.5GB，OCR 受带宽限制 |
| CPU 4C/8T | 3B active 约 7 token/s（CUDA 注意力） | active 5B 约 3–4 token/s；10B 约 1.5–2 token/s |

**判断**：

- 35B-A3B（3B active、dense 约 1.3GB）是这台机器的甜点：显存、CPU、磁盘都刚好。
- 下一个可尝试的是“总参数更大、active 仍约 3B、dense 维度/层数不显著增加”的 MoE。按公式先算，50–60B 级有机会，70B 级磁盘已不是首要问题，但 6GB 显存/带宽仍很可能挡住。
- 真正要上 70B+，优先顺序是：① 已完成的 stripped 模型（磁盘减半）；② GPU slot bank / 更激进的部分 offload；③ 硬件升级（显存/内存）。单纯“LES 省 RAM”不够。

## 5. GPU slot bank 设计（可选，未实现）

目标：把专家槽放到显存，GPU 直接算专家，而不是 CPU 算。

```text
SSD → CPU pinned staging（每槽/每层）
    → cudaMemcpyAsync（独立 stream）
    → GPU slot bank（device 内存）
    → event / graph 同步，供当前层 mul_mat_id
```

关键点：

- 槽张量必须是 CUDA device buffer；`preadv` 不能直接写，需要 H2D 拷贝。
- 拷贝必须与 ggml graph 的层顺序对齐；同步拷贝会丢失预读重叠。
- 需要 slots 的 device 侧 LRU、事件池、miss 回退、显存预算。
- 预读可以在当前层计算时异步进行，命中时直接复用 device 槽。
- 预期收益：专家计算从 CPU 转到 GPU；但每 token 仍有 100–400MB 的 PCIe 拷贝，6GB 显存也限制了窗口大小。要超过常驻 8 token/s 才有替换价值，需原型验证。
- 风险：高；建议先做单层/单模型原型，再决定是否全量。

## 6. 复用检查清单

- [ ] 新模型是标准 GGUF MoE，专家张量命名/轴符合提取器
- [ ] `experts.py extract` + `verify` 通过
- [ ] 运行时已接该架构的专家虚拟化/槽绑定
- [ ] `--moe-slot-bank` ≥ top-k，且 RAM/VRAM 预算通过
- [ ] 短文本输出与普通 mmap 一致
- [ ] 真实图 OCR / 长上下文 / 多图分别验证
- [ ] 记录磁盘、RSS、VRAM、prompt/decode t/s
- [ ] 未通过质量门不替换常驻服务

## 7. 结论

这套实现的价值不在“复现 iPad 17.39 token/s”，而在于：

1. 把 GGUF MoE 的专家资产管线、slot bank、预读/窗口、Windows 定位读做成了可复用运行时；
2. 证明了 6GB 笔记本可以用“CPU 专家槽 + GPU 注意力”跑 35B-A3B，RAM 约 3GB；
3. 给出了换模型前的容量算法和显存/磁盘/CPU 边界。

对下一个端侧模型，优先复用资产层、slot 运行时、Windows I/O 和 benchmark；模型适配层按架构单独写，不要把 qwen35moe 特判扩散到通用层。

## 8. 最新候选（2026-10-19）

| 候选 | 时间 | 与 35B-A3B 的关系 | 判断 |
|---|---|---|---|
| MiniCPM-V 4.7 35B-A3B + DSpark draft | 2026-10-16 | 同模型 + 389M draft | 可加载，但 CPU 专家槽下 1.9–2.9 token/s，低于非投机 7.0，不启用 |
| Qwen-AgentWorld-35B-A3B | 2026-06 | 同架构/同规模 | 不增加容量；质量取向不同，未测 |
| Qwen3.5-122B-A10B | 2026-04 | 同架构、更大（122B/10B active） | IQ2_XXS 36.6GB；dense 约 3.5–5GB，6GB 显存仅勉强文本，CPU 约 1.5–2 token/s，不建议 |
| Qwen3.8-Flash-Next / 2.4T-A95B | 2026-08 | `qwen4_exp`，未接 | 架构未适配，体量远超本机 |
| Hy-Memory-30B-A3B / Nemotron 3.5 30B-A3B | 2026 | 更小/不同架构 | 不增加容量；需另写适配 |
| LFM2.5-24B-A2B | 2026-10 | 更小（24B/2B active），`lfm2moe` | 纯文本；普通 llama.cpp 可跑，LES 不支持该 arch；中文改写约 13 秒，视觉需另用 v4.7/VL |

结论：当前没有“更新且更大、仍适合 6GB/16GB”的现成模型。LFM2.5-24B-A2B 是纯文本速度选项，不是 LES/更大模型答案；继续用 35B-A3B 做多模态常驻。若要 122B-A10B，只能接受约 2 token/s 的文本级速度并先解决 dense 显存。
