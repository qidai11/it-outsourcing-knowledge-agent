# Task 0 Increment Package

## 目标

把 V3.2 Task 0 的工程可冻结部分直接复制到仓库根目录。

## 包含内容

```text
docs/business/
docs/adr/0004-v1-architecture-lock.md
evaluation/datasets/v0/
scripts/validate_task0.py
```

## 应用到仓库

假设当前仓库：

```text
~/workspace/it-outsourcing-knowledge-agent
```

解压后将本包中的目录复制到仓库根目录。

## 验证

```bash
conda activate it-agent
cd ~/workspace/it-outsourcing-knowledge-agent
python scripts/validate_task0.py
```

预期：

```text
[PASS] Task 0 engineering baseline is valid
questions: 50
P0 cases : 15
```

## 提交

```bash
git status
git add docs/business docs/adr evaluation/datasets/v0 scripts/validate_task0.py
git commit -m "docs: freeze realistic small outsourcing scope"
```

## 状态定义

```text
TASK0_ENGINEERING_BASELINE = COMPLETE
TASK0_REAL_BUSINESS_VALIDATION = PENDING
```

真实访谈不能由模拟材料替代。
