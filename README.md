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
5. **LoRA 后训练**：`finetune/gemma4_qlora_recipe.py` 在 Kaggle L4x4 上做 QLoRA，提升 tool-call 精度与 patch 正确率。
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
├─ finetune/gemma4_qlora_recipe.py   # Kaggle L4x4 QLoRA 配方
├─ eval/local_harness.py             # 9 工具本地模拟器 + 编排闭环（可跑）
├─ eval/validate_zip.py              # 提交结构校验器（可跑，13 项通过）
└─ LICENSE                           # Apache-2.0（获奖许可要求）
```

## 本地开发循环（无 GPU 也能迭代）

```bash
cd gemmapilot
python eval/local_harness.py                       # 编排闭环冒烟（MockPolicy 修样本 bug）
python eval/validate_zip.py --zip submission.zip   # 结构合规校验（13 项）
# 两处全绿后，把 agent.yaml/prompts/skills/configs 打进 submission.zip
# 在 Kaggle notebook（L4x4）跑 finetune/gemma4_qlora_recipe.py 产出 adapters/main_lora
```

## 已知待验证项

- `skills:` 键的**确切取值格式**（目录路径 vs 名称）未在本地可验证——官方要求以数据集内 `HARNESS_README.md` 为准。加入竞赛并下载数据集后，请跑一次官方 `validate_submission.py` / `compile_submission` 复核。
- 真实推理质量只能在 Kaggle 容器内验证（本地 harness 只验证编排与接线）。

详见 `SUBMISSION.md`。
