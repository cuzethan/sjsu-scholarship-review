# SJSU Scholarship Application Review

AI does a first-pass rubric score of scholarship applications; a human makes the
final call. Runs alongside human review as a first-pass filter to reduce reviewer
workload.

## Phase 1 scope: SJSU General Scholarship only

Phase 1 supports **only the SJSU General Scholarship**, across both **25-26** and
**26-27**, using **one shared rubric** and **one shared prompt**. It is the
foundation for broader scholarship scoring later. Specialized/department
scholarships (Engineering, Lurie/Education, Physics) are **not supported yet** —
config stubs exist but are clearly marked unsupported.

See **[docs/phase1-sjsu-general.md](docs/phase1-sjsu-general.md)** for the full
schema, data model, scoring flow, and evaluation scope.

## Layout

```
lambdas/
  parse-applications/   S3-triggered: .xlsx -> normalized JSON -> DynamoDB (applications)
  score-applications/   DynamoDB-Stream-triggered: Bedrock scoring -> DynamoDB (scores)
prompts/                rubric prompts (SJSU General active; others unsupported stubs)
evaluation/             model-eval harness: compare models vs historical human scores
Parser/                 local parser / test harness
apps/
  web/      React + Vite dashboard
  api/      tRPC server
infra/      deployment (deferred)
materials/  s3 data mirror (gitignored)
```

## Production pipeline (phase 1)

```
.xlsx -> S3 (data/) -> parse Lambda -> sjsu-applications (PK application_key)
       -> DynamoDB Stream (batch ~5) -> score Lambda (shared rubric + Bedrock)
       -> sjsu-scores (PK application_key)
```

Production scoring uses ONLY application content + the shared rubric. It never
reads historical human score files.

## Evaluation mode (separate)

`evaluation/` compares Bedrock models against historical human scores to pick a
model. It is narrowed to SJSU General. Note: **SJSU General 26-27** can be joined
to human scores; **25-26 cannot** (its score sheet has no `Candidate` join key),
so 25-26 supports production scoring but not human comparison. See the phase-1 doc.

## Dashboard stack

React 18 · Vite 6 · Tailwind 4 · tRPC v11. No auth.

```
pnpm install
pnpm dev      # web on :3000, api on :3005
```
