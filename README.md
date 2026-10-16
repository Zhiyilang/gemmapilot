# GemmaPilot — Google × Kaggle Gemma 4 Developer Agent Competition

> **竞赛**：[Google – The Gemma 4 Developer Agent Competition](https://www.kaggle.com/competitions/gemma-4-developer-agent/overview)（主办 Google DeepMind）
> **奖金总额：$100,000** — 主榜 **$65,000**（1st **$37k** / 2nd $18k / 3rd $10k）+ Paper Track **$35,000**（可选，11-12 截止）
> **我方定位**：自主软件工程智能体（SWE agent）——在 Kaggle 气隙容器内用 **Gemma 4** 自动修复真实 Python bug（SWE-bench 风格 PASS/FAIL）
> **资格**：Kaggle 平台对中国开放（不在 OFAC 制裁清单）。⚠️ 提交前请在竞赛 **Rules** 页最终确认 China 未被排除；需 Kaggle 账号 + 可访问 Kaggle（中国网络可能需 VPN）。
> **关键日期**：报名/组队 **2026-11-25 23:59 UTC**｜最终提交 **2026-12-02 23:59 UTC**｜Paper（可选）**11-12**

---

## 官方硬规则（已逐条对齐，勿偏离）

| 项 | 官方规定 |
|---|---|
| 提交物 | `submission.zip`，**`agent.yaml` 必须在压缩包根**；可选 `configs/`、`prompts/`、`sub_agents/`、`adapters/`、`skills/` |
| 配置语言 | **Google ADK Agent Config** 规范（adk.dev/agents/config），额外限制：禁止沙箱外代码执行 |
| 基座模型 | 四选一：`gemma-4-31b-it-qat-w4a16-ct`（本仓默认）/ `12b` / `e4b` / `e2b`。**所有 agent 与 subagent 必须同一模型，不可混用** |
| LoRA | 可选；`adapters/<name>/` 内含 `adapter_config.json` + `adapter_model.safetensors`；用 `adapter: <name>` 引用，不同 agent 可用不同 adapter |
| 工具 | **仅 9 个**：run_command / read_file / edit_file / write_file / submit_patch / get_status / get_code_neighbors / search_similar_code / get_code_subgraph。自定义能力只能用 **subagent（agent_tool）** 或 **skill 脚本（在沙箱内 run_command 执行）** |
| ⚠️ 禁止 | 把 `run_skill_script` / `load_skill_resource` 声明成 tool——它们不在封闭 ToolRegistry 内，**会导致编译失败** |
| Skill | 每个 skill 为目录，含 `SKILL.md`（YAML frontmatter 必须有 `name:`），可带 `scripts/` 与 `resources/`；需在 agent 上用 `skills:` 列出 |
| 预算 | **全局 12 小时**跑完所有任务（含沙箱准备，不含补丁验证）。可用 `eval_config.yaml` 设每任务上限 |
| 评分 | 补丁应用到 issue 仓库后跑该 issue 的验证测试，**PASS/FAIL**；总分 = 通过仓库百分比 |
| 算力 | Kaggle **L4x4**（96GB 显存），**无网络** |
| 数据集 | 公开开发集 129 tasks（FastAPI / Rich / Requests / HTTPX）；隐藏测试约 120 tasks |
| 获奖许可 | 需不限制商业使用的开源许可（官方列 **Apache-2.0**）→ 本仓已附 `LICENSE` |

## 为什么我们有胜算

我们已交付 16+ 个零依赖 agent 仓库（eval 全绿、真实运行输出）。本赛把"后训练开放模型成可靠 SWE agent"作为命题，正是我们的手艺：

1. **8 阶段闭环方法论**（PERCEIVE→SEARCH→SELECT→REASON→POLICY→EXPLAIN→ACT→RECEIPT）直接映射 SWE 任务。
2. **图导航优先**：先用 `search_similar_code` / `get_code_neighbors` 定位，再改——避免盲目 patch。
3. **最小 diff + 测试回执**：只在 pytest 变绿后 `submit_patch`。
4. **反振荡**：同一处改两次无进展就 `git checkout` 重规划（小模型最常见的死循环）。
5. **LoRA 后训练 + 真实轨迹数据**：`finetune/gemma4_qlora_recipe.py` 在 Kaggle L4x4 上做 QLoRA；训练数据不是合成玩具，而是从开发集同源四仓库挖出的 59 个真实 bug-fix PR，且每个轨迹都经 `verify_trajectories.py` 验证能在真实源码上打得上去（59/59）。
6. **预算自律**：`get_status` 常态化 + `eval_config.yaml` 每任务上限，防止单任务吃掉 12 小时。

## 目录结构

```
gemmapilot/
├─ agent.yaml                    # REQUIRED 根 agent（ADK 规范：agent_class/model/instruction/tools/skills）
├─ sub_agents/code_analyzer.yaml # 只读分析子 agent（agent_tool）
├─ prompts/system.md             # 8 阶段方法论（!include）
├─ prompts/analyzer.md           # 分析子 agent 指令（!include）
├─ configs/sampling.yaml         # 生成参数（!include，低温 0.1 求稳）
├─ eval_config.yaml              # 可选每任务上限（超时/工具调用/轮次）
├─ skills/
│  ├─ repo_navigate/  SKILL.md + scripts/find_symbol.py + resources/nav_playbook.md
│  ├─ reproduce/      SKILL.md（最小复现）
│  ├─ patch/          SKILL.md（最小 diff + submit_patch）
│  └─ verify/         SKILL.md（pytest + 预算）
├─ finetune/fetch_real_tasks.py      # 从真实仓库挖 bug-fix PR -> tasks.jsonl
├─ finetune/build_trajectories.py    # gold diff -> edit_file 轨迹
├─ finetune/verify_trajectories.py   # 闸门：证明轨迹在真实源码上打得上去
├─ finetune/gemma4_qlora_recipe.py   # Kaggle L4x4 QLoRA 配方
├─ eval/local_harness.py             # 9 工具本地模拟器 + 编排闭环（可跑）
├─ eval/validate_zip.py              # 提交结构校验器（可跑，13 项通过）
└─ LICENSE                           # Apache-2.0（获奖许可要求）
```

## 训练数据管线（真实数据，非合成玩具）

公开开发集已确认为 **FastAPI / Rich / Requests / HTTPX**。LoRA 的上限由轨迹质量决定，
所以训练数据直接来自这四个仓库的真实 bug-fix PR：

```bash
export GH_TOKEN=ghp_...                     # 60 req/h(匿名) vs 5000 req/h(带 token)
python finetune/fetch_real_tasks.py --limit 25 --pages 6 --out finetune/tasks.jsonl
python finetune/verify_trajectories.py --tasks finetune/tasks.jsonl --max 59
python finetune/build_trajectories.py --tasks finetune/tasks.jsonl --out finetune/train.jsonl
```

**当前实测（2026-10-16）**：抓到 **59 个真实任务 / 1051 行真实改动**，
`verify_trajectories.py` **59/59 PASS**。

`verify_trajectories.py` 是这条管线里最重要的一环：它按 `base_sha` 拉真实源码，
用两条**互相独立**的代码路径分别得到结果——(a) 顺序应用合成出的 `edit_file` 操作，
(b) 直接应用 gold unified diff——再断言 `a == b`。任何一条轨迹若其 `old_string`
在真实文件里不存在，都会被判 FAIL 并剔除。没有这道闸门，静默产出的脏数据会
白白烧掉整个 Kaggle 微调预算。

> 数据出处：补丁片段来自上述四个上游仓库的公开合并 PR（MIT / Apache-2.0 / BSD）。
> 生成的 `tasks.jsonl` / `train.jsonl` **不入库**（可本地重生成，且属第三方派生内容），
> 推送脚本已按 `.jsonl` 与 >100KB 排除。

## 在 Kaggle 跑微调（顺序别错）

1. 把 `train.jsonl` 作为 **Kaggle Dataset** 上传（它不在 git 仓库里，见上文），挂到 notebook。
2. ⚠️ **L4 会话无网络**：`--model_id` 必须指向挂载进来的模型输入，例如
   `/kaggle/input/gemma-4/transformers/gemma-4-31b-it-qat-w4a16-ct/1`。
   确切路径以竞赛 **Data** 页为准——填错就是加载 31B 失败、白烧配额。
3. **先跑本地预检（不需要 GPU）**：
   `python finetune/gemma4_qlora_recipe.py --dry-run --data finetune/train.jsonl`
   实测：59 行 / ~8.5 万 token / 最长 3999 token / 548 个 assistant turn（489 个是工具调用）→ OK。
   负向测试确认它会拦住"缺 system / 空 system / 无 assistant turn / 超长截断"并退出 1。
4. 正式训练（脚本会先自动跑一遍预检，失败即拒绝启动）：

```bash
python finetune/gemma4_qlora_recipe.py \
  --model_id /kaggle/input/gemma-4/transformers/gemma-4-31b-it-qat-w4a16-ct/1 \
  --data /kaggle/input/gemmapilot-trajectories/train.jsonl \
  --adapter_dir /kaggle/working/adapters/main_lora \
  --lora_r 64 --lora_alpha 128 --epochs 1 --holdout 6
```

默认 `--max_len 8192`（不是 4096：最长轨迹已到 3999 token，4096 会截掉结尾的 `submit_patch`）。
默认开启 `--mask-prompt`：**只对 assistant token 计损失**，不浪费容量去背 system/user；
若分词器取不到 offset 会自动回退为全序列损失并告警。`--seed` 固定，`--holdout N` 留末尾 N 条做评估（论文消融要用）。

## 本地开发循环（无 GPU 也能迭代）

```bash
cd gemmapilot
python eval/local_harness.py                       # 编排闭环冒烟（MockPolicy 修样本 bug）
python eval/validate_zip.py --zip submission.zip   # 结构合规校验（13 项）
python finetune/verify_trajectories.py --tasks finetune/tasks.jsonl --max 20
# 三处全绿后，把 agent.yaml/prompts/skills/configs 打进 submission.zip
# 在 Kaggle notebook（L4x4）跑 finetune/gemma4_qlora_recipe.py 产出 adapters/main_lora
```

## Paper Track（$35k，**11-12 截止，比主榜早 3 周**）

官方另设论文赛道，主题含「**PEFT / RL 提升 SWE agent 能力**」——正是本仓在做的事，
且**鼓励使用官方发布的图/嵌入数据集**。需在 <https://www.kaggle.com/competitions/gemma-4-developer-agent-paper> **单独报名**。

骨架见 [`paper/OUTLINE.md`](paper/OUTLINE.md)（含可证伪性声明：若"未验证数据"训出的效果
不差于"验证过的数据"，则我们的核心贡献 1 不成立，仍如实发表）。
所有数字均为占位符，**跑完 LoRA 后必须逐个替换为实测值再投**。

## 已知待验证项

- `skills:` 键的**确切取值格式**（目录路径 vs 名称）未在本地可验证——官方要求以数据集内 `HARNESS_README.md` 为准。加入竞赛并下载数据集后，请跑一次官方 `validate_submission.py` / `compile_submission` 复核。
- 真实推理质量只能在 Kaggle 容器内验证（本地 harness 只验证编排与接线）。
- ⚠️ **不要相信二手奖金稿**：有第三方站点宣称本赛有 Unsloth / LiteRT / llama.cpp-GGUF / Best New Application 各 $10k 专项奖、且报名截止 11-02。**官方 Overview 页面均无这些奖项，报名截止为 11-25、总奖 $100k（主榜 $65k + 论文 $35k）**。一律以官方页为准。

详见 `SUBMISSION.md`。
