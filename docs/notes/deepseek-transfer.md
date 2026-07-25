# Ten failures, one shared witness

This exhibit applies the Independent Evidence Compiler's correlation question to
Murmur's two committed DeepSeek runs. It does not relabel outcomes or modify the
benchmark artifacts; it reads their append-only event logs.

The exact failure-family concentration is 0.820 because one trajectory also has
`missing_accent_red`. That extra diagnostic does not make its primary failure
independent: all 10 failed trajectories share `missing_metric_pass_hat_k`.
Treating the shared diagnostic as a common-mode cause therefore yields one
effective failure witness, not 10 independent witnesses.

Fresh output from:

```text
python scripts/transfer_deepseek_evidence.py
```

```text
| runs | attempts | passes | failures | shared diagnostic | failure concentration | effective failure witnesses |
| ---: | ---: | ---: | ---: | --- | ---: | ---: |
| 2 | 30 | 20 | 10 | missing_metric_pass_hat_k | 0.820 | 1 |
```

This is a transfer exhibit, not a new reliability estimator. The ordinary pass
counts remain 20 of 30, and the passing action paths remain structurally distinct.
The narrower conclusion is that these 10 failures provide evidence of one shared
semantic weakness, so an i.i.d. reliability projection should not count them as
10 independent root-cause observations.
