# WS8 Evaluation Benchmark V0 — B7 Freeze Review

## Decision

**PASS_READY_FOR_WS8_IMPLEMENTATION**

B7 reviewed the benchmark side only. No production code was changed and no Agent run was used.

## Q012 / Q041 metric decision

The frozen WS8 metric definition states:

```text
Current-Version Hit Rate population = cases with explicit current_doc_codes
```

Q012 and Q041 are both DELETE_PENDING exclusion-only cases and have:

```text
current_doc_codes = []
```

Therefore B7 removes `current_version_hit_rate` from both rows.

This is an applicability correction made before final benchmark handoff. It does **not** change the v1 metric formula, denominator rule, target, Gold schema, corpus facts, or fixtures.

### Q012

Before:

```text
metric_applicability = [current_version_hit_rate]
```

After:

```text
metric_applicability = []
```

Q012 remains a scorable deterministic lifecycle-behavior case. It simply does not enter a frozen aggregate acceptance metric denominator.

### Q041

Before:

```text
metric_applicability = [current_version_hit_rate, critical_regression]
```

After:

```text
metric_applicability = [critical_regression]
```

Q041 remains a P0 safety case. DELETE_PENDING exclusion is therefore still enforced by Critical Regression.

## Current-Version Hit Rate final population

The V0 Gold rows that now participate in `current_version_hit_rate` are:

```text
Q009, Q010, Q011, Q025, Q026, Q042, Q047
```

Every one of these rows has non-empty `current_doc_codes`.

## Final benchmark-side review

All blocking benchmark checks are GREEN:

- exactly 50 cases, Q001–Q050;
- no duplicate case IDs;
- Gold/project/user/behavior maps to the frozen catalog;
- Gold passes `gold-v1` JSON Schema;
- every metric applicability entry satisfies the corresponding v1 population prerequisites;
- all Gold `doc_code` references exist;
- acceptable Gold has no cross-project document;
- required normal Evidence is `PUBLISHED`;
- lifecycle/current metadata is internally consistent;
- forbidden/current Evidence sets do not conflict;
- all corpus file SHA256 values match actual bytes;
- aggregate corpus hash still matches the B5 frozen value;
- the four required Alpha/Beta identifier collisions remain present;
- SUPERSEDED / DRAFT / UNDER_REVIEW / DELETE_PENDING distractors remain present;
- all 15 P0 cases retain deterministic safety assertions and `critical_regression`;
- identity/membership fixtures remain consistent with authorization cases;
- Sandbox Issue fixture remains consistent with Issue Gold;
- all setup/fault scenario references resolve;
- fixture aggregate SHA256 still matches;
- known runtime-scope set remains exactly Q014, Q046 and Q049.

## Runtime findings handed to WS8 implementation

These are **not benchmark-side blockers** and were not “fixed” with data:

1. Q014 — fuzzy identifier suggestion/confirmation is not composed into the current QA runtime.
2. Q046 — current Run/authorization model has no first-class company-public scope.
3. Q049 — issue lookup lacks deterministic exact issue-key lookup.

Runner/report implementation must surface them as `UNSCORABLE_RUNTIME_SCOPE`, never silently skip them.

## Freeze integrity

- previous B6 Gold SHA256: `d736fde4552cd3918e280963ef8e96ef8dbe8843ce7d56a6cae541b7f429b470`
- final B7 Gold SHA256: `05e6962b927762dc85cb8f5217cf8d8970cab98b2214b92cb27aff3b3bc388b1`
- corpus changed: **NO**
- fixtures changed: **NO**
- question catalog changed: **NO**
- Gold schema changed: **NO**
- metric-definition version changed: **NO**
- benchmark-side blocker count: **0**

The benchmark is ready to hand off to the WS8 Runner / Metrics / Ablation / Report implementation.
