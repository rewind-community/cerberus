import boto3
import logging
import os
import re

logger = logging.getLogger()
client = boto3.client("sso-admin")
cloudwatch = boto3.client("cloudwatch")


def _emit_metric(name: str) -> None:
    """Emit a Cerberus operational metric (Deleted | Skipped | Failed).

    Observability must never block the deletion pipeline, so any failure here
    is logged and swallowed.
    """
    try:
        cloudwatch.put_metric_data(
            Namespace="Cerberus",
            MetricData=[{"MetricName": name, "Value": 1, "Unit": "Count"}],
        )
    except Exception as e:
        logger.warning("Failed to emit Cerberus.%s metric: %s", name, e)


def lambda_handler(event, context):
    """Cerberus Lambda function processes removal of Control Tower provisioned access.

    Parameters
    ----------
    event: dict, required
        Input event to the Lambda function

    context: object, required
        Lambda Context runtime methods and attributes

    Returns
    ------
        dict: Object containing the result of the Cerberus Lambda function.
    """
    logger.debug("Lambda function invoked with event: %s", event)
    logger.debug("Lambda function context: %s", context)

    instanceArn = event.get("DescribeInstance").get("InstanceArn")
    targetId = event.get("RequestParameters").get("targetId")
    targetType = event.get("RequestParameters").get("targetType", "AWS_ACCOUNT")
    permissionSetArn = (
        event.get("DescribePermissionSet").get("PermissionSet").get("PermissionSetArn")
    )
    permissionSetName = (
        event.get("DescribePermissionSet").get("PermissionSet").get("Name")
    )
    principalType = event.get("RequestParameters").get("principalType")
    principalId = event.get("RequestParameters").get("principalId")

    if not all(
        [
            instanceArn,
            targetId,
            permissionSetArn,
            permissionSetName,
            principalType,
            principalId,
        ]
    ):
        logger.error("Missing required parameters in the event: {}".format(event))
        _emit_metric("Failed")
        return {
            "result": "FAILED",
            "message": "Missing required parameters in the event.",
            "details": event,
        }

    if principalType not in ["USER", "GROUP"]:
        logger.error("Invalid principal type: {}".format(principalType))
        _emit_metric("Failed")
        return {
            "result": "FAILED",
            "message": f"Invalid principal type: {principalType}. Expected 'USER' or 'GROUP'.",
        }

    principalName = (
        event.get("DescribeUser").get("UserName")
        if principalType == "USER"
        else event.get("DescribeGroup").get("DisplayName")
    )
    logger.info(
        "Processing principal type ({}) '{}'.".format(principalType, principalName)
    )

    try:

        # Operational mode: ENFORCE | DRY_RUN | DISABLED. DISABLED is normally enforced at the
        # EventBridge rule level (the rule's State is DISABLED and no events reach this handler),
        # but we honour it here too as defense-in-depth against direct invocation.
        mode = os.environ.get("Mode", "ENFORCE").strip().upper()

        if mode == "DISABLED":
            logger.info(
                "Cerberus is in DISABLED mode; ignoring invocation for principal '%s'.",
                principalName,
            )
            _emit_metric("Skipped")
            return {
                "result": "SUCCESS",
                "message": "DISABLED: invocation ignored.",
                "details": {"mode": "DISABLED"},
            }

        permissionSetNamePattern = os.environ.get("PermissionSetNamePattern", "")
        principalGroupNamePattern = os.environ.get("PrincipalGroupNamePattern", "")
        principalUserNameEmail = (
            os.environ.get("PrincipalUserNameEmail", "").strip().lower()
        )

        if not permissionSetNamePattern or not principalGroupNamePattern:
            logger.error(
                "Required regex patterns missing from environment "
                "(PermissionSetNamePattern and PrincipalGroupNamePattern must be set)."
            )
            _emit_metric("Failed")
            return {
                "result": "FAILED",
                "message": "Required regex patterns missing from environment.",
            }

        permissionSetNamePatternRegex = re.compile(
            permissionSetNamePattern, re.IGNORECASE
        )
        principalGroupNameRegex = re.compile(principalGroupNamePattern, re.IGNORECASE)

        logger.info(
            "Using regex for principal name: {}".format(principalGroupNameRegex.pattern)
        )
        logger.info(
            "Using regex for permission set name: {}".format(
                permissionSetNamePatternRegex.pattern
            )
        )
        logger.info(
            "Using principal user name email: {}".format(
                principalUserNameEmail
                if principalUserNameEmail
                else "No username pattern specified"
            )
        )

        if re.match(permissionSetNamePatternRegex, permissionSetName) and (
            re.match(principalGroupNameRegex, principalName)
            or principalUserNameEmail == principalName
        ):
            if mode == "DRY_RUN":
                logger.info(
                    "DRY_RUN: would remove Control Tower provisioned '%s' access for principal '%s' on permission set '%s' targeting account '%s'.",
                    principalType,
                    principalName,
                    permissionSetName,
                    targetId,
                )
                _emit_metric("Skipped")
                return {
                    "result": "SUCCESS",
                    "message": "DRY_RUN: deletion skipped.",
                    "details": {"mode": "DRY_RUN"},
                }

            logger.info(
                "Removing Control Tower provisioned '{}' access for principal '{}'.".format(
                    principalType, principalName
                )
            )

            # DeleteAccountAssignment is async: the initial response usually returns
            # Status=IN_PROGRESS and the actual deletion completes later. Treat any non-FAILED
            # status as accepted; a synchronous Status=FAILED (rare — e.g. target out of scope)
            # or any client.exceptions.* is a real failure. See:
            # https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_DeleteAccountAssignment.html
            response = client.delete_account_assignment(
                InstanceArn=instanceArn,
                TargetId=targetId,
                TargetType=targetType,
                PermissionSetArn=permissionSetArn,
                PrincipalType=principalType,
                PrincipalId=principalId,
            )
            status_obj = response.get("AccountAssignmentDeletionStatus", {})
            status = status_obj.get("Status")
            request_id = status_obj.get("RequestId")
            logger.info(
                "Account assignment deletion request accepted (status=%s, requestId=%s).",
                status,
                request_id,
            )

            if status == "FAILED":
                failure_reason = status_obj.get("FailureReason", "unknown")
                logger.error(
                    "Account assignment deletion failed at API: %s", failure_reason
                )
                _emit_metric("Failed")
                return {
                    "result": "FAILED",
                    "message": "Account assignment deletion failed.",
                    "details": response,
                }

            # AWS documents three valid statuses for DeleteAccountAssignment:
            # IN_PROGRESS, SUCCEEDED, FAILED. Anything else (None, an unrecognized
            # string, a missing AccountAssignmentDeletionStatus) means the API
            # contract changed underneath us or the response is malformed — fail
            # closed rather than emit Deleted on a state we can't reason about.
            if status not in {"IN_PROGRESS", "SUCCEEDED"}:
                logger.error(
                    "Unexpected deletion status from API: %r (full response: %s)",
                    status,
                    response,
                )
                _emit_metric("Failed")
                return {
                    "result": "FAILED",
                    "message": "Unexpected deletion status from API: {!r}.".format(status),
                    "details": response,
                }

            _emit_metric("Deleted")
            return {
                "result": "SUCCESS",
                "message": "Account assignment deletion request accepted (status={}).".format(
                    status
                ),
                "details": response,
            }
        else:
            logger.info(
                "Principal '{}' ({}) does not match Control Tower provisioned access pattern. No action taken.".format(
                    principalName, principalType
                )
            )
            _emit_metric("Skipped")
            return {
                "result": "SUCCESS",
                "message": "No action taken for principal: {}".format(principalName),
            }

    except re.PatternError as e:
        logger.error("Invalid regex pattern: %s", e)
        _emit_metric("Failed")
        return {
            "result": "FAILED",
            "message": "Invalid regex pattern.",
            "details": str(e),
            "errorName": type(e).__name__,
        }

    except client.exceptions.ConflictException as e:
        logger.error("ConflictException occurred: %s", e)
        _emit_metric("Failed")
        return {
            "result": "FAILED",
            "message": "Conflict occurred while deleting account assignment.",
            "details": str(e),
            "errorName": type(e).__name__,
        }

    except client.exceptions.ResourceNotFoundException as e:
        logger.error("ResourceNotFoundException occurred: %s", e)
        _emit_metric("Failed")
        return {
            "result": "FAILED",
            "message": "Resource not found while deleting account assignment.",
            "details": str(e),
            "errorName": type(e).__name__,
        }

    except client.exceptions.AccessDeniedException as e:
        logger.error("AccessDeniedException occurred: %s", e)
        _emit_metric("Failed")
        return {
            "result": "FAILED",
            "message": "Access denied while deleting account assignment.",
            "details": str(e),
            "errorName": type(e).__name__,
        }

    except client.exceptions.ValidationException as e:
        logger.error("ValidationException occurred: %s", e)
        _emit_metric("Failed")
        return {
            "result": "FAILED",
            "message": "Validation error occurred while deleting account assignment.",
            "details": str(e),
            "errorName": type(e).__name__,
        }

    except Exception as e:
        logger.error("An error occurred: %s", e)
        _emit_metric("Failed")
        return {
            "result": "FAILED",
            "message": "An error occurred while processing the request.",
            "details": str(e),
            "errorName": type(e).__name__,
        }
