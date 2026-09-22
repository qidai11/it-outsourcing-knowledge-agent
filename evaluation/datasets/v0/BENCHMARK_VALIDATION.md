# WS8 Evaluation Benchmark V0 — Final Benchmark Validation

## Result

**PASS_READY_FOR_WS8_IMPLEMENTATION**

The B7 Freeze Review resolved the only known benchmark-side metric applicability inconsistency.

## Final counts

| Item | Count |
|---|---:|
| Question catalog cases | 50 |
| Gold records | 50 |
| SCORABLE cases | 47 |
| UNSCORABLE_RUNTIME_SCOPE | 3 |
| Corpus documents | 22 |
| P0 cases | 15 |
| Benchmark-side blockers | 0 |

## Freeze decision

Q012 and Q041 do not participate in `current_version_hit_rate`, because the frozen v1 definition includes only cases with explicit `current_doc_codes`.

Q041 remains covered by `critical_regression`.

There are no remaining benchmark-side blockers.

## Known runtime-scope findings

```text
Q014
Q046
Q049
```

These remain explicit `UNSCORABLE_RUNTIME_SCOPE` cases and must be reported by the future runner.

## Final hashes

- corpus aggregate SHA256: `e880c250b570f9419528b8958cec21c7a239e7394e0c8cc3d54aad1688cc9521`
- corpus manifest SHA256: `c899de928f2c48d9ef27abb3a0e5cebee8ee1aeca97e03b35e7c062a70aa1512`
- Gold manifest SHA256: `05e6962b927762dc85cb8f5217cf8d8970cab98b2214b92cb27aff3b3bc388b1`
- fixtures aggregate SHA256: `30af875821a8bf4f0bec8f2721276d7f6d05683359dcd3cbd2d958f756d0e41e`
- dataset manifest SHA256: `cb138d84f8af2e6e76c906aab9549e90668a2ed48c0f60031843b9efdbf1024d`
