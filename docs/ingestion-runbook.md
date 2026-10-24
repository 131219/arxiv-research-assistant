# arXiv Ingestion Pipeline Runbook

Last updated: 2026-08-14

## Purpose

This runbook explains how to operate, monitor, debug, resume, and
force-reprocess the arXiv ingestion pipeline.

AWS region:

us-east-1

AWS CLI profile:

arxiv-pipeline

State machine:

arn:aws:states:us-east-1:123456789012:stateMachine:arxiv-ingestion-pipeline-dev

Corpus bucket:

arxiv-bedrock-kb-123456789012

---

# 1. Normal Ingestion Run

Normal production behavior should skip archives that already have a
successful completion marker.

Create a unique run ID:

RUN_ID="arxiv-run-$(date -u +%Y%m%d-%H%M%S)"

EXECUTION_ARN=$(AWS_PAGER="" aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:123456789012:stateMachine:arxiv-ingestion-pipeline-dev \
  --name "$RUN_ID" \
  --input "{
    \"run_id\": \"$RUN_ID\",
    \"year\": 2026,
    \"month\": 6,
    \"archive_limit\": 1,
    \"skip_completed\": true,
    \"max_concurrency\": 1,
    \"output_bucket\": \"arxiv-bedrock-kb-123456789012\"
  }" \
  --region us-east-1 \
  --profile arxiv-pipeline \
  --query 'executionArn' \
  --output text)


echo "$EXECUTION_ARN"

Important:

The corpus is currently intentionally frozen.

Do not run additional real ingestion jobs unless explicitly intended.

# 2. Forced Reprocessing

Use this only when an archive must intentionally be processed again.

Set:

"skip_completed": false

Example:

RUN_ID="forced-reprocess-$(date -u +%Y%m%d-%H%M%S)"


EXECUTION_ARN=$(AWS_PAGER="" aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:123456789012:stateMachine:arxiv-ingestion-pipeline-dev \
  --name "$RUN_ID" \
  --input "{
    \"run_id\": \"$RUN_ID\",
    \"year\": 2026,
    \"month\": 6,
    \"archive_limit\": 1,
    \"skip_completed\": false,
    \"max_concurrency\": 1,
    \"output_bucket\": \"arxiv-bedrock-kb-123456789012\"
  }" \
  --region us-east-1 \
  --profile arxiv-pipeline \
  --query 'executionArn' \
  --output text)


echo "$EXECUTION_ARN"

Behavior:

skip_completed=true
→ completed archive is skipped.

skip_completed=false
→ existing success marker does not stop the worker.
→ archive is processed again.
→ success marker is rewritten using the current schema.

# 3. Monitor Step Functions

Check current execution status:

AWS_PAGER="" aws stepfunctions describe-execution \
  --execution-arn "$EXECUTION_ARN" \
  --region us-east-1 \
  --profile arxiv-pipeline \
  --query '{status:status,startDate:startDate,stopDate:stopDate,error:error,cause:cause}'

macOS does not normally include the watch command.

Use this polling loop instead:

while true; do
  STATUS=$(AWS_PAGER="" aws stepfunctions describe-execution \
    --execution-arn "$EXECUTION_ARN" \
    --region us-east-1 \
    --profile arxiv-pipeline \
    --query 'status' \
    --output text)


  echo "$(date '+%H:%M:%S')  $STATUS"


  [[ "$STATUS" != "RUNNING" ]] && break


  sleep 15
done
# 4. Inspect Execution History
AWS_PAGER="" aws stepfunctions get-execution-history \
  --execution-arn "$EXECUTION_ARN" \
  --reverse-order \
  --max-results 30 \
  --region us-east-1 \
  --profile arxiv-pipeline

This is useful for identifying which state failed.

# 5. Distributed Map Failure

If the parent execution fails with:

States.ExceedToleratedFailureThreshold

find the Distributed Map Run:

MAP_RUN_ARN=$(AWS_PAGER="" aws stepfunctions list-map-runs \
  --execution-arn "$EXECUTION_ARN" \
  --region us-east-1 \
  --profile arxiv-pipeline \
  --query 'mapRuns[0].mapRunArn' \
  --output text)


echo "$MAP_RUN_ARN"

Find failed child executions:

AWS_PAGER="" aws stepfunctions list-executions \
  --map-run-arn "$MAP_RUN_ARN" \
  --status-filter FAILED \
  --region us-east-1 \
  --profile arxiv-pipeline \
  --query 'executions[].{name:name,arn:executionArn,status:status}' \
  --output table

Save one failed child ARN:

CHILD_ARN=$(AWS_PAGER="" aws stepfunctions list-executions \
  --map-run-arn "$MAP_RUN_ARN" \
  --status-filter FAILED \
  --region us-east-1 \
  --profile arxiv-pipeline \
  --query 'executions[0].executionArn' \
  --output text)


echo "$CHILD_ARN"

Inspect the child failure:

AWS_PAGER="" aws stepfunctions get-execution-history \
  --execution-arn "$CHILD_ARN" \
  --reverse-order \
  --max-results 30 \
  --region us-east-1 \
  --profile arxiv-pipeline
# 6. Batch Failure

A failed child execution usually contains:

Batch Job ID
Batch JobDefinition revision
container command
exit code
CloudWatch log stream name

Inspect a Batch job:

AWS_PAGER="" aws batch describe-jobs \
  --jobs <JOB_ID> \
  --region us-east-1 \
  --profile arxiv-pipeline

Important fields:

status
statusReason
container.exitCode
container.logStreamName
container.command
jobDefinition
parameters
# 7. Read Batch CloudWatch Logs

Log group:

/aws/arxiv-pipeline/dev

Example:

AWS_PAGER="" aws logs get-log-events \
  --log-group-name /aws/arxiv-pipeline/dev \
  --log-stream-name <LOG_STREAM_NAME> \
  --region us-east-1 \
  --profile arxiv-pipeline \
  --query 'events[].message' \
  --output text

This should be checked before changing code.

A previously discovered example was:

exec /usr/local/bin/python: exec format error

That was caused by an image/runtime CPU architecture mismatch.

Current Batch architecture is:

X86_64
# 8. Check Current Batch Deployment
AWS_PAGER="" aws batch describe-job-definitions \
  --job-definition-name arxiv-pipeline-job-dev \
  --status ACTIVE \
  --region us-east-1 \
  --profile arxiv-pipeline \
  --query 'sort_by(jobDefinitions,&revision)[-1].{
    Revision:revision,
    Architecture:containerProperties.runtimePlatform.cpuArchitecture,
    Image:containerProperties.image,
    ProcessorVersion:containerProperties.environment[?name==`PROCESSOR_VERSION`].value | [0]
  }'

Expected:

Architecture = X86_64
Image tag = Git commit SHA
PROCESSOR_VERSION = same Git commit SHA
# 9. Success Marker

Archive success markers are stored at:

status/arxiv/<archive_id>/_SUCCESS.json

Example:

AWS_PAGER="" aws s3 cp \
  s3://arxiv-bedrock-kb-123456789012/status/arxiv/arXiv_pdf_2606_001/_SUCCESS.json \
  - \
  --profile arxiv-pipeline

A current valid marker should contain fields including:

expected_item_count
discovered_pdf_count
successful_count
failed_count
markdown_object_count
metadata_object_count
failure_rate
maximum_failure_rate
output_validation_passed

For a clean archive:

successful_count == discovered_pdf_count
failed_count == 0
markdown_object_count == successful_count
metadata_object_count == successful_count
output_validation_passed == true
# 10. Central Validation Report

Validation reports are stored under:

reports/<run_id>/validation-report.json

Example:

AWS_PAGER="" aws s3 cp \
  "s3://arxiv-bedrock-kb-123456789012/reports/$RUN_ID/validation-report.json" \
  - \
  --profile arxiv-pipeline

Important fields include:

validation_passed
expected_archive_count
valid_archive_count
invalid_archive_count
expected_pdf_count
successful_pdf_count
failed_pdf_count

Do not start Bedrock ingestion when centralized validation fails.

# 11. DynamoDB Processing Ledger

Processing state is stored in:

arxiv-archive-processing-dev

Inspect an archive:

AWS_PAGER="" aws dynamodb get-item \
  --table-name arxiv-archive-processing-dev \
  --key '{
    "archive_id": {
      "S": "arXiv_pdf_2606_001"
    }
  }' \
  --region us-east-1 \
  --profile arxiv-pipeline

Typical states include:

RUNNING
COMPLETE
FAILED

The ledger also tracks processing attempts and counts.

# 12. Bedrock Knowledge Base

Knowledge Base:

YOUR_KB_ID

Data Source:

YOUR_DATA_SOURCE_ID

Inspect ingestion jobs:

AWS_PAGER="" aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id YOUR_KB_ID \
  --data-source-id YOUR_DATA_SOURCE_ID \
  --region us-east-1 \
  --profile arxiv-pipeline

A successful pipeline requires Bedrock ingestion to reach a successful
completion state and document failures to be zero.

# 13. Resume After Failure

Normal recovery strategy:

Identify the failed Step Functions state.
If failure occurred inside Distributed Map, identify failed child.
Inspect Batch job.
Inspect CloudWatch container logs.
Fix the actual root cause.
Deploy the fix through CI/CD.
Re-run the pipeline with:
"skip_completed": true

Already-completed archives should be skipped.

This prevents unnecessary reprocessing.

# 14. Force Refresh a Legacy Archive

If a legacy _SUCCESS.json does not contain the modern validation
fields, run that archive with:

"skip_completed": false

The worker should process the archive again and rewrite its success
marker.

This behavior was proven with:

arXiv_pdf_2606_001

Result:

132 discovered
132 successful
0 failed
132 Markdown
132 metadata
output_validation_passed=true
# 15. CI/CD

A push to main currently performs:

Ruff
→ pytest
→ Python syntax validation
→ CloudFormation linting
→ Docker builds
→ GitHub OIDC authentication to AWS
→ push/reuse immutable ECR Git-SHA image
→ deploy arxiv-processing-dev
→ deploy arxiv-workflow-dev
→ verify deployed Batch image == github.sha

Do not manually replace the production Batch image after CI deployment.

# 16. Important Operational Rule

The corpus is currently frozen while the MCP/product layer is being
built.

Do NOT run the full June 2026 ingestion/backfill unless explicitly
decided.

The original June scope is approximately:

239 TAR archives
31,999 PDFs
126.6 GB

# 17. Debugging Principle

Always diagnose from evidence in this order:

Step Functions parent
→ Distributed Map child
→ AWS Batch job
→ CloudWatch log
→ application exception

Do not modify infrastructure or application code until the actual
failure is identified.
