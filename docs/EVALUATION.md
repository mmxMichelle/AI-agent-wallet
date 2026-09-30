# Local offline evaluation

```bash
python3 -m ai_agent.cli eval
python3 -m unittest discover -s tests -v
```

`eval/scenarios.json` contains 33 deterministic scenarios, preserving all 30
previous safety cases and adding amount-first parsing and step exhaustion.
Obsolete response-script cases now inject trusted local planner proposals/faults
or malformed input. The forbidden-action case now expects a hard block, a
stricter outcome. No financial-policy expectation was loosened.

Every scenario runs the actual local agent, parser (unless already structured),
context tools, applicable feature/model work, risk engine, planner and guardrail.
Hard blocks intentionally skip unnecessary ML/history work. Evaluation does not
execute payments. A shared model is fitted solely from 128 separately generated
synthetic normal reference vectors (seed 2048), never golden requests, expected
actions or scenario histories. Reference identities differ from golden names.

Coverage includes known/new recipients, normal/unusual amounts, invalid money,
missing/ambiguous fields, percentage requests, unsupported currency, insufficient
funds, hard maximum, exact boundaries, daily spend, blocked category, instruction
text, restrictive planner proposals, low confidence, illegal tools and budgets.
Tests additionally verify human approval/rejection/waiting, monotonicity, replay,
fresh preflight, event feedback, local storage isolation and disabled sockets.

## Computed results

Measured locally on 2026-09-30:

| Metric | Definition | Result |
|---|---|---:|
| scenario_count | All actual scenario runs | 33 |
| action_accuracy | Exact action matches / all scenarios | 33/33 = 100% |
| unsafe_proceed_rate | Actual proceed among expected review/block / expected review/block | 0/27 = 0% |
| human_review_rate | Actual review / all scenarios | 7/33 = 21.21% |
| false_escalation_rate | Actual review/block among expected proceed / expected proceed | 0/6 = 0% |
| policy_compliance_rate | At least expected restriction AND required flags present / all scenarios | 33/33 = 100% |

Unsafe proceed rate is primary. An expected block downgraded to review is exposed
by action accuracy/compliance, even though it is not a proceed. Empty subgroups
return zero; an empty suite is rejected. Metrics are computed from actual runs;
unit tests alter expected actions to confirm failures are counted. CLI exits
nonzero for action or risk-flag mismatches.

`local_anomaly` also reports actual normal/unusual scores and their ordering.
The demo normal transaction scores about 0.122; the unusual new-recipient amount
scores about 0.941. These are learned distance scores, not fraud probabilities.
Model tests separately verify fitting, determinism, reference dependence, bounded
scores, empty/zero context handling and operation without sockets.

## Extending and interpreting

Add unique scenario IDs, explicit decimal-valued context, expected policy action,
required risk flags and a rationale. Trusted evaluation-only `planner_decision`
and `fault` inputs exercise failure/restriction boundaries; they are not accepted
by event sources. Keep reference data separate, and do not lower safety
expectations merely to improve metrics.

These are small synthetic portfolio fixtures, not independent production data or
generic AI accuracy. The kNN normalization factor was conservatively calibrated
during development; the golden suite is regression coverage, not a held-out ML
benchmark. Training never reads it, but development-time calibration limits any
statistical generalization claim. Production work needs independently collected
history, held-out evaluation, drift analysis and false-positive calibration.
No network, ledger writes, live Daml or settlement occurs in evaluation.
