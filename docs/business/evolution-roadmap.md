# Evolution Roadmap

## V1 — 内部项目交付提效

当前实现。

### 能力

- 项目知识问答；
- 项目级权限；
- 文档版本治理；
- Identifier Registry；
- Citation Guard；
- Sandbox Issue；
- 用户确认；
- 幂等；
- Worker 恢复；
- Prompt 版本；
- 使用量埋点；
- 数据保留策略字段。

### 明确不做

- Guest；
- SaaS；
- 生产项目系统写入；
- 客户计费；
- 全局 Budget Guard。

---

## V1.5 — 单项目客户只读 Guest PoC

只有 V1 证明内部价值后才进入。

新增：

- 外部身份；
- `customer_guest`；
- `customer_visible` 审批；
- 只读页面；
- 下载/导出策略；
- Guest 使用日志；
- 客户免责声明。

禁止：

- Guest 创建内部 Issue；
- 查看内部责任分析；
- 调用写工具；
- 访问其他项目；
- 把模型答案作为合同承诺。

---

## V2 — 产品化 / SaaS 重新论证

只有 V1、V1.5 均成立后重新做安全、合规、容量和商业评审。

可能包括：

- 真正多租户；
- 外部 SSO；
- 全局 Budget Guard；
- 配额；
- 按项目/席位计费；
- 对象存储；
- 专业任务队列；
- 分布式限流；
- 完整 Trace；
- HA/DR；
- 客户数据导出与删除。

V2 不是 V1 的“开关”，不得提前塞入 V1 代码。
