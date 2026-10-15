# GemmaPilot — Google × Kaggle Gemma 4 Developer Agent Competition

> **竞赛**：[Google – The Gemma 4 Developer Agent Competition](https://www.kaggle.com/competitions/gemma-4-developer-agent/overview)
> **奖金池**：≈ **$110,000**（主榜 Top3 $65k：$30k/$20k/$15k；4 个专项 bounty 各 $10k；Paper Track $35k 单独）
> **我方定位**：自主软件工程智能体（SWE agent）——在 Kaggle 容器内用 **Gemma 4 31B** 自动修复真实 Python bug（SWE-bench Verified 风格）
> **资格**：Kaggle 平台对中国开放（不在 OFAC 制裁清单）。⚠️ 需 Kaggle 账号 + 可访问 Kaggle（中国网络可能需 VPN）。**参赛前请于竞赛 Rules 页最终确认 China 未被排除。**
> **关键日期**：报名/组队截止 **2026-11-25 23:59 UTC**｜最终提交 **2026-12-02 23:59 UTC**

---

## 为什么我们有胜算

我们已交付 16+ 个零依赖 agent 仓库（eval 全绿、真实运行输出、闭环方法论 PERCEIVE→SEARCH→SELECT→REASON→POLICY→EXPLAIN→ACT→RECEIPT）。本赛把"后训练开放模型成可靠 SWE agent"作为核心命题——这正是我们的手艺：

1. **方法论可迁移**：8 阶段闭环直接映射 SWE 任务（定位→复现→修→验证→回执）。
2. **工具编排到位**：竞赛 harness 提供 9 个工具（run_command / read_file / edit_file / write_file / submit_patch / get_status / get_code_neighbors / search_similar_code / get_code_subgraph），我们已为其写好 skills + 编排逻辑。
3. **LoRA 后训练**：官方允许并鼓励对 `gemma-4-31b-it-qat-w4a16-ct` 做 PEFT/LoRA，提升 tool-call 精度与 patch 正确率——我们给出 Kaggle 免费 GPU 微调配方。
4. **预算自律**：`get_status` 暴露预算消耗，编排层据此收敛探索，避免超支被判失败。

## 硬性规则（必须遵守）

| 项 | 规定 |
|---|---|
| 基座模型 | **唯一** `gemma-4-31b-it-qat-w4a16-ct`（Gemma 4 31B Instruct, QAT W4A16）。**禁止**用 Claude/Gemini/其他 frontier API 作 agent 核心 |
| LoRA | 允许，`.safetensors` 放 `adapters/<name>/`（含 `adapter_config.json`），可在 `agent.yaml` 与 `sub_agents/*.yaml` 分别引用不同 adapter |
| 提交物 | 容器内 `agent.yaml` + `sub_agents/*.yaml` + `skills/*/SKILL.md` + `adapters/*`；`!include` 指令相对当前文件解析 |
| 沙箱 | 禁止路径穿越（`../`/symlink 越出提交根），tools 在 `/workspace` 内执行 |
| 算力 | 竞赛提供 **Kaggle L4x4** 机器（4×L4 ≈ 96GB）——微调与推理都在容器内完成 |

## 目录结构

```
gemmapilot/
├─ agent.yaml                 # 根 coder agent：model + system prompt + 工具白名单
├─ sub_agents/analyzer.yaml   # 只读分析子 agent（可选独立 LoRA）
├─ prompts/system.md          # 8 阶段方法论 system prompt（!include 加载）
├─ skills/
│  ├─ repo_navigate/SKILL.md  # 用 get_code_neighbors / search_similar_code 定位
│  ├─ reproduce/SKILL.md      # 写最小复现测试
│  ├─ patch/SKILL.md          # edit_file/write_file + submit_patch
│  └─ verify/SKILL.md         # run_command pytest + get_status 预算自律
├─ finetune/gemma4_qlora_recipe.py  # Kaggle L4x4 上的 QLoRA 微调配方
├─ eval/local_harness.py      # 本地 9 工具模拟器 + 样本 bug，离线迭代编排
└─ SUBMISSION.md              # 你需执行的人工动作清单
```

## 本地开发循环

```bash
cd gemmapilot
python eval/local_harness.py        # 离线跑编排逻辑（mock model），验证 tools/skills 接线
# 调好编排后，把 prompts/system.md + skills 直接拷进 Kaggle 提交目录
# 在 Kaggle notebook 跑 finetune/gemma4_qlora_recipe.py 产出 adapters/main_lora
```

详见 `SUBMISSION.md`。
