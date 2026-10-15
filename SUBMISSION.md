# GemmaPilot — 提交动作清单（你需做的真人步骤）

> 本赛与已有 13 条赛线不同：**核心在容器内后训练 + 编排**，且运行在 Kaggle。AI 已写好全部可提交物（agent.yaml / skills / prompts / 微调配方 / 离线测试台）。你只做下面几步。

## 资格预检（先做）
1. 打开 https://www.kaggle.com/competitions/gemma-4-developer-agent/overview → **Rules** 页，确认 **China 未被排除**（Kaggle 通常对中国开放，但请以官方 Rules 为准）。
2. 确保有 **Kaggle 账号**，且网络可访问 Kaggle（中国可能需 VPN）。

## 提交流程
1. **报名/组队**：2026-11-25 23:59 UTC 前在 Kaggle 点击 "Join Competition" 并组队（≤5 人，可单人）。
2. **克隆本仓到 Kaggle**：把 `agent.yaml` + `sub_agents/` + `prompts/` + `skills/` 拷进提交目录；`adapters/` 暂空（先跑基座无 LoRA 验证编排）。
3. **（可选但强烈建议）训练 LoRA**：在 Kaggle notebook（L4x4）跑 `finetune/gemma4_qlora_recipe.py`，产出 `adapters/main_lora/`（adapter_config.json + adapter_model.safetensors）。再用 `analyzer_lora` 训练只读分析子 agent。
4. **构建数据集**：用 SWE-bench-style 轨迹构造 `train.jsonl`（messages: system+user(issue+图快照+工具)→assistant(单次工具调用/编辑)）。这是拉开差距的关键。
5. **本地先验证**：提交前在本地跑 `python eval/local_harness.py` 确认编排闭环正常（已通过）。
6. **提交容器**：按 HARNESS_README 打包 agent.yaml + adapters，Kaggle 在 L4x4 上自动评测（隐藏测试仓 pass@1）。最终提交截止 **2026-12-02 23:59 UTC**。
7. **预算自律**：评测按预算计费，`get_status` 显示在编排里已实现——别超支。

## 奖金映射
- 主榜 Top3：**$30k / $20k / $15k**
- 专项 bounty（各 $10k）：LiteRT Edge / llama.cpp·GGUF / **Unsloth Fine-Tuning（我们配方命中）** / Best New Application
- 合计 ≈ **$110k**

## 风险
- ⚠️ 需可用的 Kaggle 访问 + 训练算力（Kaggle 免费 L4x4 足够 QLoRA 31B）。
- ⚠️ 若 China 在 Rules 被排除 → 立即放弃本线，不浪费算力。
- ⚠️ 真实评测在 Kaggle 容器内，本地 harness 只验证编排，不验证 Gemma 推理质量（需 Kaggle 内真跑）。
