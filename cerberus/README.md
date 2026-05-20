# Cerberus

Cerberus is an [AWS Serverless Application Model](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-getting-started.html) (SAM) application that automatically removes unwanted AWS Control Tower default IAM Identity Center permission set assignments. It listens for `sso:CreateAccountAssignment` events on CloudTrail and, when an assignment matches the configured regex patterns, calls `sso-admin:DeleteAccountAssignment` to remove it.

![Cerberus SAM ASL](../static/stepfunctions_graph.png)

## Why this runs in the AWS Organization management account

Cerberus must be deployed in the AWS Organization **management account**, not in a delegated administrator account.

[AWS IAM Identity Center](https://docs.aws.amazon.com/singlesignon/latest/userguide/delegated-admin.html) supports delegating administration to a member account, and that's the recommended pattern for most identity-management workloads. However, IAM Identity Center enforces a service-level restriction that is invisible to IAM policies, SCPs, and the delegation configuration:

> Permission sets whose lifecycle is owned by the management account — including all the AWS-managed permission sets that AWS Control Tower provisions (`AWSAdministratorAccess`, `AWSReadOnlyAccess`, `AWSOrganizationsFullAccess`, etc.) — can only have their assignments removed by a principal in the management account itself.

Attempting to delete these assignments from a delegated administrator account returns `AccessDeniedException` regardless of IAM permissions. Since Cerberus's purpose is precisely to clean up these AWS-Control-Tower-managed default assignments, it must run in the management account.

This is a deliberate architectural compromise. The mitigations below (permission boundary, kill switch, expanded alarms, reduced concurrency) are designed to limit the blast radius of a compromised Cerberus deployment.

The "protected target" account (the one whose assignments the state machine always skips before invoking the Lambda) is derived automatically from `AWS::AccountId` at deploy time — there is no operator-supplied account ID parameter, which eliminates the misconfiguration vector where the wrong account is marked protected and the real management account becomes vulnerable to self-lockout.

## Pre-deploy security checklist

Before deploying Cerberus to the management account, confirm:

- [ ] **CloudTrail** is enabled at the organization level and ingests `sso.amazonaws.com` events.
- [ ] **CloudTrail data events** are enabled on the Cerberus Lambda function ARN — this captures invocation and code-change activity. Configure post-deploy.
- [ ] **GuardDuty Lambda Protection** is enabled (verify org-level coverage).
- [ ] **Branch protection on `main`** in the source repository: required reviewers, required status checks, signed commits required, no force-push, no admin bypass.
- [ ] **CODEOWNERS** routes Cerberus changes through your security and platform teams.
- [ ] **Deploying principal** is a dedicated `CerberusDeployer` role in the management account, not `AdministratorAccess`. The role itself should have a permission boundary.
- [ ] **NotificationEmail** is wired to a real on-call destination (PagerDuty, monitored shared inbox), not a personal email.

## CloudFormation Template Parameters

Defined in `template.yaml`. Parameters without a `Default` are required at deploy time.

### `Mode` (optional, default `ENFORCE`)

Operational mode of the deletion pipeline:

| Value | Behavior |
|---|---|
| `ENFORCE` | Default. Cerberus deletes matching assignments. |
| `DRY_RUN` | Lambda evaluates the regex and logs what *would* be deleted, but does not call the SSO API. Use for the first 24 hours after deploying or after changing a regex pattern. |
| `DISABLED` | EventBridge rule's `State` is set to `DISABLED`. No events reach the state machine. Operational kill switch. |

Flip via `sam deploy --parameter-overrides Mode=DRY_RUN` (or `=DISABLED`, `=ENFORCE`) without changing code.

### `PermissionSetNamePattern` (optional)

Regex matched (case-insensitive) against the permission set name. Default matches the AWS Control Tower default permission sets (`AWSOrganizationsFullAccess`, `AWSReadOnlyAccess`, `AWSServiceCatalogEndUserAccess`, `AWSServiceCatalogAdminFullAccess`, `AWSPowerUserAccess`, `AWSAdministratorAccess`).

### `PrincipalGroupNamePattern` (optional)

Regex matched (case-insensitive) against the principal name when `principalType=GROUP`. Default matches the AWS Control Tower default groups.

### `PrincipalUserNameEmail` (optional, default empty)

Exact email address (lowercase) matched against the principal name when `principalType=USER`. Used to clean up the default Account Factory admin user assignment created during account provisioning. Leave empty to disable user-email matching.

### `NotificationEmail` (required)

Email address subscribed to the SNS topic that receives all alarm notifications.

### `LogGroupName` (optional, default `/cerberus`)

Name of the CloudWatch Log Group for the Cerberus state machine and Lambda.

### `LogGroupRetentionDays` (optional, default 14)

CloudWatch Log retention period.

## Monitoring and alerts

Cerberus publishes four CloudWatch Alarms, all wired to the same SNS topic:

| Alarm | Source metric | Threshold | What it means |
|---|---|---|---|
| `CerberusExecutionFailureAlarm` | `AWS/States ExecutionsFailed` | > 0 in 1 min | A state machine execution failed. Real deletion failure or upstream issue. |
| `CerberusFunctionErrorsAlarm` | `AWS/Lambda Errors` | > 0 in 1 min | Lambda raised an unhandled error. Code-level issue. |
| `CerberusFunctionThrottlesAlarm` | `AWS/Lambda Throttles` | > 0 in 1 min | Reserved-concurrency cap hit. Investigate event burst. |
| `CerberusHighDeletionRateAlarm` | `AWS/States ExecutionsSucceeded` | > 10 in 5 min | Cerberus is deleting at unusual volume. Possible regex misfire or compromise. |

Subscribe `NotificationEmail` to a real on-call destination — a noisy alarm to a personal inbox is worse than no alarm.

## Permission boundary

The template ships an inline `AWS::IAM::ManagedPolicy` (`CerberusPermissionsBoundary`) attached to both the Lambda execution role and the state machine role. It allows only the specific actions required for IAM Identity Center cleanup:

- `sso:DeleteAccountAssignment`
- `sso:DescribePermissionSet`, `sso:DescribeInstance`, `sso:ListPermissionSets`, `sso:GetPermissionSet`, `sso:DescribePermissionSetProvisioningStatus`
- `identitystore:DescribeUser`, `identitystore:DescribeGroup`
- `lambda:InvokeFunction`
- `logs:CreateLogStream`, `logs:PutLogEvents`, `logs:DescribeLogGroups`, `logs:DescribeLogStreams`
- `cloudwatch:PutMetricData`

Anything else (`iam:*`, `organizations:*`, `sts:AssumeRole`, `sso:CreateAccountAssignment`, `kms:*`, etc.) is implicitly denied at the boundary regardless of inline policy grants.

Service Control Policies do **not** apply to management-account principals. The permission boundary is the only IAM-layer guardrail and is intentionally tight.

## Build and Deploy

### Build

```bash
sam build
```

Container builds are configured by default in `samconfig.toml`. The build runs inside `public.ecr.aws/sam/build-python3.13` so the artifact matches the Lambda runtime exactly.

### Deploy (first time)

The recommended pattern is to deploy in `DRY_RUN` mode first, observe, then flip to `ENFORCE`.

```bash
sam deploy --region <region> \
  --parameter-overrides \
    NotificationEmail=<oncall-destination@example.com> \
    Mode=DRY_RUN \
    PrincipalUserNameEmail=<account-factory-admin@example.com>
```

Watch the `/cerberus` log group for `DRY_RUN: would remove ...` lines on the next `CreateAccountAssignment` event. Confirm the matches are correct.

Then flip to `ENFORCE`:

```bash
sam deploy --parameter-overrides Mode=ENFORCE [...other params...]
```

To override the regex defaults:

```bash
sam deploy --region <region> \
  --parameter-overrides \
    NotificationEmail=<oncall-destination@example.com> \
    PermissionSetNamePattern='^AWS(?:OrganizationsFullAccess|ReadOnlyAccess|...)$' \
    PrincipalGroupNamePattern='^AWS(?:LogArchiveAdmins|ControlTowerAdmins|...)$' \
    PrincipalUserNameEmail='<account-factory-admin@example.com>'
```

### Operational kill switch

```bash
# Stop processing events without deleting the stack
sam deploy --parameter-overrides Mode=DISABLED [...other params...]

# Resume
sam deploy --parameter-overrides Mode=ENFORCE [...other params...]
```

`DISABLED` sets the EventBridge rule's `State` to `DISABLED`. No events reach the state machine.

## Migration from the delegated-admin model

Earlier versions of Cerberus deployed the state machine and Lambda in a delegated administrator account, with a separate `cft-eventbridge-rule.yaml` template forwarding events from the management account. That topology is no longer supported — see [Why this runs in the management account](#why-this-runs-in-the-aws-organization-management-account).

Migration sequence:

1. Deploy this stack to the management account in `Mode=DRY_RUN`.
2. Validate the new stack against a test `CreateAccountAssignment`. Confirm the Lambda logs `DRY_RUN: would remove ...` and no actual deletion occurs.
3. Delete the old delegated-admin stack (`sam delete --stack-name cerberus` from the delegated admin account profile).
4. Delete the old management-account forwarder stack (the one created from `cft-eventbridge-rule.yaml`).
5. Flip the new stack to `Mode=ENFORCE`.
6. Validate the end-to-end path against another test `CreateAccountAssignment`. Confirm the assignment is actually removed in the IAM Identity Center console — do not rely on the Lambda's reported result alone.

The `DRY_RUN` overlap (steps 1–3) is what makes the cutover safe: both stacks are subscribed to the same event source, but neither modifies state during the overlap window.

## Testing

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r tests/requirements.txt
AWS_DEFAULT_REGION=<region> python3 -m unittest discover -v
```

`AWS_DEFAULT_REGION` is required because `app.py` initialises a `boto3.client("sso-admin")` at import time.

## Cleanup

```bash
sam delete --stack-name "cerberus"
```

This removes the Lambda, state machine, EventBridge rule, log group, alarms, SNS topic, and permission boundary policy. CloudTrail data event configuration (if any) is org-level and must be removed separately.

## CloudWatch MCP Server

The repo includes a pre-configured CloudWatch MCP server (`.mcp.json`) that gives Claude Code live read access to the deployed Cerberus stack — Step Functions execution history, Lambda logs, and CloudWatch metrics — without leaving the editor.

### AWS Profile Setup

The server expects a local AWS CLI profile named **`cerberus`** with read-only CloudWatch access **in the management account** (where this stack is now deployed). Create it using IAM Identity Center or a dedicated IAM user/role:

```bash
# Option A — SSO profile (recommended)
aws configure sso --profile cerberus

# Option B — static credentials
aws configure --profile cerberus
```

Attach the AWS managed policy `arn:aws:iam::aws:policy/CloudWatchLogsReadOnlyAccess` to whichever principal the profile authenticates as. The MCP server only needs read access; do not grant write or broader permissions.

The server targets `ca-central-1` by default (set in `.mcp.json`). If your stack is in a different region, update `AWS_REGION` in `.mcp.json` accordingly.

### What it gives you

Once the profile is configured, Claude Code can query the `/cerberus` log group directly to:

- Inspect Lambda invocation results and errors
- Trace Step Functions execution failures end-to-end
- Pull CloudWatch alarm history
