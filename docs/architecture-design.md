# Design: arXiv Ingestion and Bedrock Knowledge Base Pipeline

**Diagram:** [Design Inspector — ArXiv_Bedrock_KB_Ingestion_Pipeline](https://design-inspector.a2z.com/?#IArXiv_Bedrock_KB_Ingestion_Pipeline)

## 1. Objective

Build an AWS-native pipeline that:

1. Starts an initial arXiv backfill on demand or on a schedule.
2. Uses Amazon EventBridge Scheduler to start the workflow.
3. Uses AWS Step Functions (Standard Workflow) to coordinate the pipeline.
4. Uses AWS Batch on AWS Fargate to run parallel document-processing jobs.
5. Writes normalized, retrieval-ready documents to Amazon S3.
6. Starts an Amazon Bedrock Knowledge Bases ingestion job.
7. Makes the processed scientific-paper corpus available for semantic retrieval and RAG.

The design deliberately separates **data acquisition and transformation** (Batch/Fargate)
from **embedding and indexing** (Bedrock Knowledge Bases).

## 2. High-Level Architecture

```text
Manual trigger or EventBridge schedule
        |
        v
AWS Step Functions (Standard)
        |
        v
Discover source archives (FetchManifest / BuildWorkList)
        |
        v
Distributed Map fan-out  --->  AWS Batch job queue  --->  AWS Batch on Fargate
                                                              |
                              +-------------------------------+
                              |
              Read arXiv S3 (Requester Pays)
                              |
              Extract, parse, normalize papers
                              |
              Write Markdown + metadata sidecars to S3
                              |
              Validation and completion manifest
                              |
                              v
              Bedrock Knowledge Bases: StartIngestionJob
                              |
              Chunking -> embeddings -> vector index
                              |
                              v
              Retrieve / RetrieveAndGenerate (RAG)
```

## 3. AWS Services and Responsibilities

| Service | Responsibility |
|---|---|
| Amazon EventBridge Scheduler | Starts the initial backfill or later incremental workflow |
| AWS Step Functions (Standard) | Coordinates discovery, fan-out, Batch execution, validation, retries, and Bedrock ingestion |
| AWS Batch | Queues and schedules document-processing jobs |
| AWS Fargate | Runs each Batch container without managing EC2 instances |
| Amazon ECR | Stores the document-processing container image |
| Amazon S3 | Stores manifests, transformed documents, metadata sidecars, status markers, and reports |
| Amazon DynamoDB (optional) | Processing ledger for idempotency and archive status |
| Amazon Bedrock Knowledge Bases | Chunks documents, creates embeddings, indexes into the vector store |
| Amazon OpenSearch Serverless | Vector index backing the Knowledge Base |
| Amazon CloudWatch | Logs, metrics, alarms, Step Functions execution history |
| AWS KMS | Encrypts S3 data, logs, and other supported resources |
| Amazon SNS (optional) | Failure and completion notifications |

## 4. Key Design Decisions

### 4.1 Bucket topology: two buckets, one owned

| Bucket | Owner | Contents | Access |
|---|---|---|---|
| arXiv source bucket | arXiv (third-party, Requester Pays) | PDF TAR archives, metadata manifest | Read-only, `RequestPayer=requester` on every request |
| `research-corpus` | Us | All pipeline output, separated by prefix | Read/write, prefix-scoped IAM |

The `research-corpus` bucket is **not** limited to structured documents. Prefix layout:

```text
s3://research-corpus/
├── control/         # manifests, work-list JSONL files
├── raw/             # OPTIONAL retained TAR copies (skipped when streaming)
├── staging/         # temporary per-run extraction output
├── knowledge-base/  # arxiv/papers/YYMM/<id>.md + <id>.md.metadata.json
├── status/          # per-archive _SUCCESS.json / _FAILURE.json markers
└── reports/         # run summaries, failed-items.jsonl
```

With the recommended streaming strategy (process one TAR member at a time, discard
temp files), `raw/` is unused and no TAR files are stored on our side.

**Constraint:** the Bedrock data source points only at
`s3://research-corpus/knowledge-base/arxiv/`. Raw TARs, staging output, and control
manifests are never visible to the Knowledge Base, even though they share a bucket.

### 4.2 Processing unit: one TAR archive per Batch job

One AWS Batch job per arXiv TAR archive for the initial implementation. Rationale:

- **Clean idempotency unit** — `_SUCCESS.json` markers, checksum comparison, and
  retries all key off a single archive ID.
- **Cheap retries** — a failed job retries exactly one archive.
- **Predictable sizing** — one archive drives the 4 vCPU / 16 GiB / 100 GiB
  ephemeral-storage job definition.
- **Failure isolation** — the per-paper failure threshold (≤ 2% warn, > 2% fail)
  applies per archive.
- **Natural fan-out** — Distributed Map emits one work item per archive.

Batching multiple TARs per job is mechanically easy later (Distributed Map
`ItemBatcher` / `MaxItemsPerBatch`) but only pays off if task-startup overhead
dominates processing time. Since arXiv TARs (~500 MB, hundreds of papers) take far
longer to process than a Fargate task takes to start, keep one-per-job through the
pilot and revisit only if Phase 2 measurements say otherwise.

### 4.3 Why each service

- **EventBridge** — clean trigger for one-time, scheduled, and incremental modes.
- **Step Functions** — visible workflow state, Distributed Map fan-out, retries,
  `batch:submitJob.sync` integration, long-running coordination, Bedrock ingestion
  coordination.
- **AWS Batch** — durable job queue, retries, job definitions, Fargate scheduling,
  isolation between archive-processing jobs.
- **Fargate** — no ECS/EC2 cluster management for v1; compare with Batch on EC2 Spot
  after the pilot for very large corpora.
- **Bedrock Knowledge Bases last** — Batch workers focus on transformation; Bedrock
  owns chunking, embeddings, vector indexing, and retrieval. No duplicate embedding
  logic in containers.

## 5. Step Functions Workflow

```text
InitializeRun
  -> FetchManifest              (small Batch job or SDK integration; versioned copy to control/)
  -> BuildWorkList              (JSONL of archives needing work; skip when _SUCCESS.json exists
                                 and source checksum unchanged)
  -> ProcessArchivesWithDistributedMap
       ItemReader: s3:getObject (JSONL work list)
       MaxConcurrency: 10–25 initially
       ItemProcessor: batch:submitJob.sync   (one job per archive, 3 retries w/ backoff)
  -> ValidateOutputs            (archive/paper counts, sidecar counts, malformed docs,
                                 duplicates, error rate)
       -- failures found --> WriteFailureReport -> FailExecution
  -> StartBedrockIngestion      (bedrockagent:startIngestionJob; knowledgeBaseId + dataSourceId)
  -> PollBedrockIngestion       (Wait/Choice loop on getIngestionJob:
                                 STARTING|IN_PROGRESS -> wait; COMPLETE -> continue;
                                 FAILED|STOPPED -> fail)
  -> PublishRunSummary
  -> Success
```

The same state machine serves both modes via input: `{"mode": "INITIAL_BACKFILL"}`
or `{"mode": "INCREMENTAL"}`.

## 6. Batch Job Contract

Input per job:

```json
{
  "runId": "backfill-2026-07-18",
  "sourceBucket": "arxiv",
  "sourceKey": "pdf/arXiv_pdf_2607_001.tar",
  "requestPayer": "requester",
  "destinationBucket": "research-corpus",
  "destinationPrefix": "knowledge-base/arxiv/papers/",
  "statusPrefix": "status/arxiv/"
}
```

Job behavior:

1. Skip if `_SUCCESS.json` exists and source checksum + processor version match.
2. Stream the TAR; for each member: extract → parse (PyMuPDF / optional GROBID, OCR
   fallback) → normalize to Markdown → generate metadata sidecar → upload both →
   release temp file.
3. Write archive-level `_SUCCESS.json` (paper counts, checksum, processor version).
4. Per-paper failures go to `reports/<runId>/failed-items.jsonl`; archive fails only
   when the failure rate exceeds the threshold.

Initial sizing: 4 vCPU, 16 GiB memory, 100 GiB ephemeral storage, 2–4 h timeout,
3 retry attempts. Fargate On-Demand for the pilot; Fargate Spot for retry-safe runs
once jobs are proven idempotent.

## 7. Document Format

One normalized Markdown file per paper plus a metadata sidecar:

```text
knowledge-base/arxiv/papers/2607/2607.12345.md
knowledge-base/arxiv/papers/2607/2607.12345.md.metadata.json
```

Sidecar `metadataAttributes` include: `arxiv_id`, `title`, `authors`,
`primary_category`, `categories`, `publication_year`, `published_date`, `source`,
`document_type` — enabling retrieval filters by year, category, author, etc.
Validate against the current Bedrock metadata specification during implementation.

Chunking: let Bedrock handle it (fixed-size or hierarchical) for v1. Do not generate
embeddings in the Fargate job.

## 8. Idempotency

- Archive level: `status/arxiv/<archiveId>/_SUCCESS.json` with source checksum and
  processor version; a changed processor version intentionally triggers reprocessing.
- Paper level: deterministic object keys from the canonical arXiv ID so retries
  overwrite instead of duplicating.
- Optional DynamoDB ledger mirrors archive status for fast work-list construction.

## 9. Security and IAM

Separate roles for: EventBridge → Step Functions; Step Functions → Batch;
Batch execution (ECR pull, logs); job containers (S3 read source / write destination);
Bedrock KB → S3 prefix; Step Functions → Bedrock ingestion APIs.

- Job role: `s3:GetObject/HeadObject/ListBucket/PutObject/AbortMultipartUpload`,
  KMS encrypt/decrypt/generate, CloudWatch Logs write. Writes restricted to required
  prefixes.
- Requester Pays: every source-bucket request sets `RequestPayer=requester`.
- Network: Fargate tasks in private subnets; NAT or VPC endpoints (S3 gateway,
  ECR API/Docker, CloudWatch Logs, Secrets Manager if used).
- KMS customer-managed keys for S3 data and logs.

## 10. Observability

- Metrics: archives discovered/submitted, jobs running/failed, papers
  processed/failed, per-archive duration, bytes read/written, ingestion duration and
  failures.
- Structured logs per container entry: `runId`, `archiveId`, `paperId`, `stage`,
  `status`, `durationMs`.
- Alarms: excessive Batch failures, failed executions, ingestion failure, no-progress,
  Fargate quota exhaustion, high parse-failure rate. SNS for notifications.

## 11. Rollout Plan

| Phase | Scope | Concurrency | Goal |
|---|---|---|---|
| 1 | 1 archive | 1 | Validate Requester Pays, networking, storage, output format, ingestion, retrieval |
| 2 | 10–20 archives | 2–5 | Cost/throughput/failure-rate baselines |
| 3 | 100–500 archives | 10–25 | Retry behavior, quotas, Distributed Map, S3 throughput, ingestion at scale |
| 4 | Full backfill | Gradual increase | Bounded by Fargate vCPU quota, per-job vCPU, source behavior, budget |
| 5 | Incremental | Daily schedule | Process only new/changed papers; same workflow, `mode=INCREMENTAL` |

## 12. Deployment Order

1. S3 bucket and prefixes → 2. KMS keys → 3. ECR repository → 4. Build/push parser
image → 5. Batch Fargate compute environment → 6. Batch job queue → 7. Job
definitions (manifest + parser) → 8. Bedrock Knowledge Base → 9. Bedrock S3 data
source → 10. Step Functions state machine → 11. EventBridge Scheduler →
12. CloudWatch alarms + SNS → 13. One-archive test → 14. Small pilot →
15. Controlled full backfill.

## 13. References

### AWS documentation

- EventBridge starting Step Functions workflows:
  https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-cloudwatch-events-s3.html
- Step Functions and AWS Batch integration:
  https://docs.aws.amazon.com/step-functions/latest/dg/connect-batch.html
- Step Functions `.sync` service-integration pattern:
  https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html
- AWS Batch jobs on Fargate:
  https://docs.aws.amazon.com/batch/latest/userguide/fargate-job-definitions.html
- Fargate ephemeral storage for Batch:
  https://docs.aws.amazon.com/batch/latest/APIReference/API_EphemeralStorage.html
- Bedrock Knowledge Base S3 connector:
  https://docs.aws.amazon.com/bedrock/latest/userguide/s3-data-source-connector.html
- Bedrock Knowledge Base chunking:
  https://docs.aws.amazon.com/bedrock/latest/userguide/kb-chunking.html
- Bedrock custom transformation:
  https://docs.aws.amazon.com/bedrock/latest/userguide/kb-custom-transformation.html
- Start a Bedrock ingestion job (`StartIngestionJob`):
  https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_StartIngestionJob.html
- Bedrock metadata sidecars:
  https://docs.aws.amazon.com/bedrock/latest/userguide/kb-metadata.html

### Design artifacts

- Architecture diagram (Design Inspector):
  https://design-inspector.a2z.com/?#IArXiv_Bedrock_KB_Ingestion_Pipeline
