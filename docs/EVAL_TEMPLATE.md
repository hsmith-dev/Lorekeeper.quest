# {{title}}

<!--
Report skeleton for the eval scripts in src/backend/scripts/ (built on
eval_common.py). eval_common.write_report creates a missing report from this
file, then on every run rewrites ONLY the two generated regions below
(eval:results and eval:failures). Everything else is hand-written: fill it in
once and it is never touched again. Keep the section order of
docs/RETRIEVAL_EVAL.md.
-->

What this evaluates, against which data (normally the demo Campaign in
`seeds/demo_campaign.json`), and which script produces it.

## Method

- **Cases**: the labelled inputs, how many, and how they were chosen.
- **Metrics**: each column of the results table, and what "higher" means.
- **Operating points**: what the sweep varies.

## Results

<!-- eval:results -->
_Not run yet. The next run of the eval script writes its table here._
<!-- /eval:results -->

**Chosen:** the operating point marked in the table, and why it beats its
neighbours.

## What these numbers validate

The part of the system the eval exercises, step by step.

## Measured failure modes this process caught and fixed

| Failure (measured) | Fix |
|---|---|
| | |

### Failures at the chosen point (latest run)

<!-- eval:failures -->
_Not run yet._
<!-- /eval:failures -->

## Reproducing

```bash
# Seed the demo Campaign (idempotent; prints its id)
python scripts/seed_demo.py

# Run the eval and refresh this report
python scripts/<eval_script>.py --campaign-id <campaign-uuid> --out docs/<NAME>_EVAL.md
```
