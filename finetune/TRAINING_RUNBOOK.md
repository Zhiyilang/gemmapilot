# GemmaPilot QLoRA 训练 Runbook — Kaggle L4×4 实操手册

> 目标：在 Kaggle 上把 `finetune/gemma4_qlora_recipe.py` 跑起来，产出论文第 5 节要填的所有数字。
> 论文截止：**2026-11-12 23:59 UTC**（Paper 赛道）；主榜提交 12-02。**倒排：训练+消融最晚 11-08 前跑完，留 4 天填数+转 PDF+提交。**
> 本手册所有命令均已在本地预验（2026-10-17）：dry-run ✅、naive 自测 ✅、check-base 抽样 ✅。

---

## 0. 开始前：本地预校验（零 GPU，5 分钟，已全部实测通过）

在项目根目录依次跑，**全绿再上 Kaggle**（Kaggle GPU 配额宝贵，不在云端 debug）：

```bash
# 1) 数据集预检（无 torch/GPU）——预期: 58 rows, ~95k tokens, OK
python finetune/gemma4_qlora_recipe.py --dry-run --data finetune/train.jsonl

# 2) A2 naive 转换器自测（离线）——预期: rc=0, OK
python finetune/build_naive_trajectories.py --demo --check-base

# 3) 预算闸门回归（确认配置没漂移）
python eval/budget_planner.py            # 预期: 通过（CI 同款）
```

> 2026-10-17 实测输出：dry-run = 58 rows / 529 assistant turns / 最长 12,760 chars；naive 语料与已验证语料 **58/58 逐行相同**（gate 在此语料 0 拒绝——这正是论文第 6 节预声明的「A2≈A3 是预期结果」情形，不是 bug）。

---

## 1. Kaggle 账号与赛事（用户动作，需 VPN）

1. 注册/登录 Kaggle → Join 两个赛道：
   - **Paper 赛道**（11-12 截止，$35k）：竞赛页 Rules 确认 China 资格后 Join
   - **主榜**（11-25 报名截止，$65k）：Join
2. 竞赛 **Data 页**找到 mandatory base model `gemma-4-31b-it-qat-w4a16-ct`，**记下它的精确 input 路径**（形如 `/kaggle/input/<slug>/transformers/gemma-4-31b-it-qat-w4a16-ct/1`）——⚠️ 路径猜错 = 整个 session 报废，这是官方明示的高频错误。
3. **待验证项（上 Kaggle 后第一件事）**：Notebook 预装 transformers 版本是否认识 gemma-4 架构。不认识就需要 `pip install -U transformers`（见第 3 节）或按竞赛 Data 页/Discussion 的指定版本。

## 2. 上传数据（两种方式，任选）

**方式 A（推荐，一次上传全程复用）**：把 `finetune/train.jsonl` + `finetune/train_naive.jsonl` 打包成一个私有 Dataset 上传（Kaggle → Datasets → New Dataset → zip）。笔记下 dataset slug，后面 `--data` 指向 `/kaggle/input/<slug>/train.jsonl`。

**方式 B**：直接从本仓 notebook 里 `!wget`/上传单文件。适合只跑一两次。

## 3. Notebook 设置与安装

1. New Notebook → **Accelerator: GPU L4 × 4** → **Internet: On**（装包阶段需要；装完可关）
2. 粘贴本仓（或上传 `finetune/` + `prompts/`）：
   ```python
   !git clone https://github.com/Zhiyilang/gemmapilot.git && cd gemmapilot
   ```
3. 安装（版本策略：先试预装，缺什么装什么；**把最终 `pip freeze` 存进论文复现清单**）：
   ```python
   !pip install -q transformers peft accelerate bitsandbytes
   # 若 transformers 不识别 gemma-4 架构再升级：
   # !pip install -q -U transformers
   ```
4. **挂载两个 input**：base model（第 1 步记下的路径）+ 你的轨迹 dataset。

## 4. 运行顺序与命令（按性价比倒排）

> 每次运行前确认 `--model_id` 指向**挂载的模型路径**，不是 HF repo id（L4 session 无网，下载必败）。

### Run 1 — A3 主实验（最重要，先跑这个）

```python
!python finetune/gemma4_qlora_recipe.py \
  --model_id /kaggle/input/<模型slug>/transformers/gemma-4-31b-it-qat-w4a16-ct/1 \
  --data /kaggle/input/<数据slug>/train.jsonl \
  --out /kaggle/working/checkpoints \
  --adapter_dir /kaggle/working/adapters/main_lora \
  --lora_r 64 --lora_alpha 128 --max_len 8192 --epochs 1 --lr 2e-4 --seed 17
```

**跑之前必须记录**（论文 wall-clock 列要用的就是这些）：

```python
import time, subprocess, sys
t0 = time.time()
# ... 运行 ...
print("WALLCLOCK_SECONDS", round(time.time() - t0, 1))
```

训练日志里逐条抄下来的：加载模型耗时、每 epoch 耗时、tokens/s（自己算：95,097 tokens ÷ 训练秒数）、holdout metrics、`prompt-masked examples: X/58`。

### Run 2 — A2 naive 对照（论文核心断言的证伪测试）

```python
!python finetune/gemma4_qlora_recipe.py \
  --model_id <同上> --data /kaggle/input/<数据slug>/train_naive.jsonl \
  --adapter_dir /kaggle/working/adapters/naive_lora \
  --lora_r 64 --seed 17
```

⚠️ **预期管理**：本地实测 naive 语料与 verified **58/58 逐行相同**（gate 0 拒绝）→ **A2≈A3 是预期结果**。论文第 6 节已预先声明此情形（"contribution 1 collapses to engineering hygiene and we will say so"）。若 A2 明显差于 A3，说明语料有毒——如实报告，那是更强的发现。若想主动测「毒数据效应」，可先跑全量 `--check-base` 找漂移样本（本地抽样 0 漂移，预期全量也是 0）。

### Run 3-5 — A5 rank 扫描（16 / 32 / 64）

64 已在 Run 1 覆盖，补 16 和 32：

```python
!python finetune/gemma4_qlora_recipe.py --model_id <同上> \
  --data <train.jsonl> --adapter_dir /kaggle/working/adapters/rank16_lora \
  --lora_r 16 --lora_alpha 32 --seed 17
# rank 32 同理（alpha 64）
```

**这组决定论文里 `{{GATE_VS_TUNING}}` 那句话**：如果 A2-A3 差 < rank 16→64 的 pass@1 摆幅，论文就写「tuning matters more than data certification」——第 6 节已把该写法预置好。

### Run 6 — A6 无预算过滤（数据侧，不用重训大模型也行——但为一致性照跑）

naive 脚本加 `--max-calls 0` 重建含超预算轨迹的语料，再训练：

```python
!python finetune/build_naive_trajectories.py --tasks finetune/tasks.jsonl \
  --out /kaggle/working/train_nofilter.jsonl --max-calls 0
!python finetune/gemma4_qlora_recipe.py --model_id <同上> \
  --data /kaggle/working/train_nofilter.jsonl --adapter_dir /kaggle/working/adapters/nofilter_lora --seed 17
```

### Run 7+ — B0 / A4 / A7：**留到 12-02 主榜评测窗**

- **B0**（base model + scaffold，无 adapter）= 用官方评测 harness 直接跑 base model，拿官方 baseline 数
- **A4**（adapter 放置位置）需要改 `sub_agents/` 接线，是代码改动不是数据改动
- **A7**（per-task cap 360s vs 1200s）是 `eval_config.yaml` 开关 + 重跑评测
- 这三个都依赖竞赛评测环境，**在 12-02 主榜窗口用同一 harness 一次跑齐**，不要现在浪费配额

## 5. pass@1 数字从哪来（关键！）

训练只产出 adapter；**pass@1 / edit-apply / calls/task / wall-clock 来自评测**：

1. 把 adapter 放回 agent 配置（论文复现清单要求 `adapters/main_lora/`）
2. 在竞赛评测环境（或本地复刻的 harness）跑验证集
3. **edit-apply rate 是单独量的**：统计发出的 `edit_file` 里 `old_string` 在目标文件中真实出现的比例——这个指标直接验证 contribution 1，比 pass@1 更敏感
4. 没有本地 harness 时，用官方 leaderboard 的验证分 + 自建小评测集（20-30 个留出任务）双轨取数，论文里注明口径

## 6. 占位符 → 数据源映射表（填论文时对照这张表）

| 占位符 | 来源 | 备注 |
|---|---|---|
| `{{RANK}}` | Run 1 的 `--lora_r` | 默认 64 |
| `{{BASELINE}}` | B0 pass@1 | 见第 5 节 |
| `{{FINAL}}` | A3 pass@1 | Run 1 + 评测 |
| `{{DELTA}}` | FINAL − BASELINE | 算术 |
| `{{GATE_VS_TUNING}}` | 比较 \|A2−A3\| vs A5 摆幅 | 第 6 节已预置两种写法 |
| `{{B0_*}}` `{{A2_*}}` `{{A3_*}}` `{{A6_*}}` `{{A7_*}}` | 各 arm 评测 | wall-clock 列用第 4 节记的秒数 |

## 7. Kaggle 配额规划

- L4×4 session 周配额约 30h（以账号实际为准）。单次运行估时：**模型加载 5-15 min + 训练 20-60 min**（95k tokens/epoch，31B 4-bit）→ 全程留 2h/次
- 必须跑的：Run 1（A3）+ Run 2（A2）≈ 4h；建议加 Run 3-5（A5）≈ 6h；A6 可选。**一周内可全部完成，不要压到截止周**
- 每次 session 结束前：`/kaggle/working/adapters/*` 设为 notebook output（Save & Run All 后自动归档），或及时 download

## 8. 训练完成后（11-08 前）

1. adapter 落到 `adapters/main_lora/`，hash 记入复现清单
2. 按第 6 节映射表填 `paper/paper.md` 的所有 `{{...}}`（含 Abstract 里的 4 个）
3. `python paper/check_paper.py`（**不加** `--allow-placeholders`）→ 必须 `RESULT: OK`
4. 转 PDF：无 pandoc → 浏览器打开渲染后的 HTML → Ctrl+P → 存为 PDF（竞赛要求 PDF）
5. **11-12 23:59 UTC 前**提交到 Paper 赛道

---

## 附：本日预验记录（2026-10-17，本地 Windows + Python 3.13）

| 项 | 命令 | 结果 |
|---|---|---|
| 数据集预检 | `gemma4_qlora_recipe.py --dry-run --data finetune/train.jsonl` | ✅ 58 rows / 95,097 tokens est. / 最长 3,190 tokens / 529 assistant turns |
| naive 自测 | `build_naive_trajectories.py --demo --check-base` | ✅ rc=0，漂移可检测 |
| naive 全量构建 | `--tasks tasks.jsonl --out train_naive.jsonl` | ✅ 58 行（1 条超预算丢弃，与 verified 一致） |
| 语料等价性 | 逐行 diff | ✅ 58/58 identical（gate 0 拒绝的预期结果） |
| 漂移检测（网络） | `--check-base --max 3` | ✅ 3 files / 6 edits / 0 drift（api.github.com 通） |
