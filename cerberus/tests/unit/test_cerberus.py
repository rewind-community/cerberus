import unittest
from unittest.mock import patch, MagicMock
from cerberus.src.cerberus.app import lambda_handler
import os


class TestLambdaHandler(unittest.TestCase):

    def tearDown(self):
        # Mode is set by individual tests when they need DRY_RUN; remove it
        # afterwards so it doesn't leak into the next test (which expects ENFORCE
        # behavior, the os.environ.get default).
        os.environ.pop("Mode", None)

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_successful_deletion(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        event = {
            "DescribeInstance": {
                "InstanceArn": "arn:aws:sso:::instance/sso-instance-id"
            },
            "RequestParameters": {
                "targetId": "target-id",
                "targetType": "AWS_ACCOUNT",
                "principalType": "USER",
                "principalId": "user-id",
            },
            "DescribePermissionSet": {
                "PermissionSet": {
                    "PermissionSetArn": "arn:aws:sso:::permissionSet/sso-instance-id/permission-set-id",
                    "Name": "MatchingPermissionSetName",
                }
            },
            "DescribeUser": {"UserName": "matchinguser@example.com"},
        }
        os.environ["PermissionSetNamePattern"] = "^MatchingPermissionSetName$"
        os.environ["PrincipalGroupNamePattern"] = "^MatchingGroupName$"
        os.environ["PrincipalUserNameEmail"] = "matchinguser@example.com"
        mock_client.delete_account_assignment.return_value = {
            "AccountAssignmentDeletionStatus": {"Status": "SUCCEEDED"}
        }
        result = lambda_handler(event, None)
        self.assertEqual(result["result"], "SUCCESS")
        self.assertIn("SUCCEEDED", result["message"])
        self.assertIn("AccountAssignmentDeletionStatus", result["details"])
        mock_cloudwatch.put_metric_data.assert_called_once_with(
            Namespace="Cerberus",
            MetricData=[{"MetricName": "Deleted", "Value": 1, "Unit": "Count"}],
        )

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_no_action_taken(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        event = {
            "DescribeInstance": {
                "InstanceArn": "arn:aws:sso:::instance/sso-instance-id"
            },
            "RequestParameters": {
                "targetId": "target-id",
                "targetType": "AWS_ACCOUNT",
                "principalType": "USER",
                "principalId": "user-id",
            },
            "DescribePermissionSet": {
                "PermissionSet": {
                    "PermissionSetArn": "arn:aws:sso:::permissionSet/sso-instance-id/permission-set-id",
                    "Name": "NonMatchingPermissionSet",
                }
            },
            "DescribeUser": {"UserName": "nonmatchinguser@example.com"},
        }
        os.environ["PermissionSetNamePattern"] = "^MatchingPermissionSetName$"
        os.environ["PrincipalGroupNamePattern"] = "^MatchingGroupName$"
        os.environ["PrincipalUserNameEmail"] = "matchinguser@example.com"
        mock_client.delete_account_assignment.return_value = {
            "AccountAssignmentDeletionStatus": {"Status": "SUCCEEDED"}
        }
        result = lambda_handler(event, None)
        self.assertEqual(result["result"], "SUCCESS")
        self.assertIn("No action taken for principal", result["message"])
        mock_cloudwatch.put_metric_data.assert_called_once_with(
            Namespace="Cerberus",
            MetricData=[{"MetricName": "Skipped", "Value": 1, "Unit": "Count"}],
        )

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_regex_pattern_error(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        event = {
            "DescribeInstance": {
                "InstanceArn": "arn:aws:sso:::instance/sso-instance-id"
            },
            "RequestParameters": {
                "targetId": "target-id",
                "targetType": "AWS_ACCOUNT",
                "principalType": "USER",
                "principalId": "user-id",
            },
            "DescribePermissionSet": {
                "PermissionSet": {
                    "PermissionSetArn": "arn:aws:sso:::permissionSet/sso-instance-id/permission-set-id",
                    "Name": "MatchingPermissionSetName",
                }
            },
            "DescribeUser": {"UserName": "matchinguser@example.com"},
        }
        os.environ["PermissionSetNamePattern"] = "["
        os.environ["PrincipalGroupNamePattern"] = "^MatchingGroupName$"
        os.environ["PrincipalUserNameEmail"] = "matchinguser@example.com"
        mock_client.delete_account_assignment.return_value = {
            "AccountAssignmentDeletionStatus": {"Status": "SUCCEEDED"}
        }
        result = lambda_handler(event, None)
        self.assertEqual(result["result"], "FAILED")
        self.assertIn("Invalid regex pattern", result["message"])

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_in_progress_status(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        event = {
            "DescribeInstance": {
                "InstanceArn": "arn:aws:sso:::instance/sso-instance-id"
            },
            "RequestParameters": {
                "targetId": "target-id",
                "targetType": "AWS_ACCOUNT",
                "principalType": "USER",
                "principalId": "user-id",
            },
            "DescribePermissionSet": {
                "PermissionSet": {
                    "PermissionSetArn": "arn:aws:sso:::permissionSet/sso-instance-id/permission-set-id",
                    "Name": "MatchingPermissionSetName",
                }
            },
            "DescribeUser": {"UserName": "matchinguser@example.com"},
        }
        os.environ["PermissionSetNamePattern"] = "^MatchingPermissionSetName$"
        os.environ["PrincipalGroupNamePattern"] = "^MatchingGroupName$"
        os.environ["PrincipalUserNameEmail"] = "matchinguser@example.com"
        mock_client.delete_account_assignment.return_value = {
            "AccountAssignmentDeletionStatus": {
                "Status": "IN_PROGRESS",
                "RequestId": "11111111-2222-3333-4444-555555555555",
            }
        }
        result = lambda_handler(event, None)
        self.assertEqual(result["result"], "SUCCESS")
        self.assertIn("IN_PROGRESS", result["message"])
        self.assertIn("AccountAssignmentDeletionStatus", result["details"])
        mock_client.delete_account_assignment.assert_called_once()

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_status_failed(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        event = {
            "DescribeInstance": {
                "InstanceArn": "arn:aws:sso:::instance/sso-instance-id"
            },
            "RequestParameters": {
                "targetId": "target-id",
                "targetType": "AWS_ACCOUNT",
                "principalType": "USER",
                "principalId": "user-id",
            },
            "DescribePermissionSet": {
                "PermissionSet": {
                    "PermissionSetArn": "arn:aws:sso:::permissionSet/sso-instance-id/permission-set-id",
                    "Name": "MatchingPermissionSetName",
                }
            },
            "DescribeUser": {"UserName": "matchinguser@example.com"},
        }
        os.environ["PermissionSetNamePattern"] = "^MatchingPermissionSetName$"
        os.environ["PrincipalGroupNamePattern"] = "^MatchingGroupName$"
        os.environ["PrincipalUserNameEmail"] = "matchinguser@example.com"
        mock_client.delete_account_assignment.return_value = {
            "AccountAssignmentDeletionStatus": {
                "Status": "FAILED",
                "FailureReason": "Target account is out of scope.",
                "RequestId": "99999999-2222-3333-4444-555555555555",
            }
        }
        result = lambda_handler(event, None)
        self.assertEqual(result["result"], "FAILED")
        self.assertIn("Account assignment deletion failed", result["message"])
        self.assertIn("AccountAssignmentDeletionStatus", result["details"])

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_unknown_status_fails_closed(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        event = {
            "DescribeInstance": {
                "InstanceArn": "arn:aws:sso:::instance/sso-instance-id"
            },
            "RequestParameters": {
                "targetId": "target-id",
                "targetType": "AWS_ACCOUNT",
                "principalType": "USER",
                "principalId": "user-id",
            },
            "DescribePermissionSet": {
                "PermissionSet": {
                    "PermissionSetArn": "arn:aws:sso:::permissionSet/sso-instance-id/permission-set-id",
                    "Name": "MatchingPermissionSetName",
                }
            },
            "DescribeUser": {"UserName": "matchinguser@example.com"},
        }
        os.environ["PermissionSetNamePattern"] = "^MatchingPermissionSetName$"
        os.environ["PrincipalGroupNamePattern"] = "^MatchingGroupName$"
        os.environ["PrincipalUserNameEmail"] = "matchinguser@example.com"
        # AWS returns a status outside the documented {IN_PROGRESS, SUCCEEDED, FAILED} set —
        # could mean API contract drift or a malformed response. Must fail closed, not emit Deleted.
        mock_client.delete_account_assignment.return_value = {
            "AccountAssignmentDeletionStatus": {"Status": "UNKNOWN_NEW_STATUS"}
        }
        result = lambda_handler(event, None)
        self.assertEqual(result["result"], "FAILED")
        self.assertIn("Unexpected deletion status", result["message"])
        mock_cloudwatch.put_metric_data.assert_called_once_with(
            Namespace="Cerberus",
            MetricData=[{"MetricName": "Failed", "Value": 1, "Unit": "Count"}],
        )

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_missing_status_fails_closed(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        event = {
            "DescribeInstance": {
                "InstanceArn": "arn:aws:sso:::instance/sso-instance-id"
            },
            "RequestParameters": {
                "targetId": "target-id",
                "targetType": "AWS_ACCOUNT",
                "principalType": "USER",
                "principalId": "user-id",
            },
            "DescribePermissionSet": {
                "PermissionSet": {
                    "PermissionSetArn": "arn:aws:sso:::permissionSet/sso-instance-id/permission-set-id",
                    "Name": "MatchingPermissionSetName",
                }
            },
            "DescribeUser": {"UserName": "matchinguser@example.com"},
        }
        os.environ["PermissionSetNamePattern"] = "^MatchingPermissionSetName$"
        os.environ["PrincipalGroupNamePattern"] = "^MatchingGroupName$"
        os.environ["PrincipalUserNameEmail"] = "matchinguser@example.com"
        # No AccountAssignmentDeletionStatus at all — Status resolves to None.
        mock_client.delete_account_assignment.return_value = {}
        result = lambda_handler(event, None)
        self.assertEqual(result["result"], "FAILED")
        self.assertIn("Unexpected deletion status", result["message"])
        mock_cloudwatch.put_metric_data.assert_called_once_with(
            Namespace="Cerberus",
            MetricData=[{"MetricName": "Failed", "Value": 1, "Unit": "Count"}],
        )

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_access_denied(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        event = {
            "DescribeInstance": {
                "InstanceArn": "arn:aws:sso:::instance/sso-instance-id"
            },
            "RequestParameters": {
                "targetId": "target-id",
                "targetType": "AWS_ACCOUNT",
                "principalType": "USER",
                "principalId": "user-id",
            },
            "DescribePermissionSet": {
                "PermissionSet": {
                    "PermissionSetArn": "arn:aws:sso:::permissionSet/sso-instance-id/permission-set-id",
                    "Name": "MatchingPermissionSetName",
                }
            },
            "DescribeUser": {"UserName": "matchinguser@example.com"},
        }
        os.environ["PermissionSetNamePattern"] = "^MatchingPermissionSetName$"
        os.environ["PrincipalGroupNamePattern"] = "^MatchingGroupName$"
        os.environ["PrincipalUserNameEmail"] = "matchinguser@example.com"

        AccessDeniedException = type("AccessDeniedException", (Exception,), {})
        mock_client.exceptions.AccessDeniedException = AccessDeniedException
        mock_client.exceptions.ConflictException = type(
            "ConflictException", (Exception,), {}
        )
        mock_client.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )
        mock_client.exceptions.ValidationException = type(
            "ValidationException", (Exception,), {}
        )
        mock_client.delete_account_assignment.side_effect = AccessDeniedException(
            "User is not authorized to perform this action."
        )

        result = lambda_handler(event, None)
        self.assertEqual(result["result"], "FAILED")
        self.assertEqual(result["errorName"], "AccessDeniedException")
        self.assertIn("Access denied", result["message"])
        mock_cloudwatch.put_metric_data.assert_called_once_with(
            Namespace="Cerberus",
            MetricData=[{"MetricName": "Failed", "Value": 1, "Unit": "Count"}],
        )

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_disabled_mode(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        event = {
            "DescribeInstance": {
                "InstanceArn": "arn:aws:sso:::instance/sso-instance-id"
            },
            "RequestParameters": {
                "targetId": "target-id",
                "targetType": "AWS_ACCOUNT",
                "principalType": "USER",
                "principalId": "user-id",
            },
            "DescribePermissionSet": {
                "PermissionSet": {
                    "PermissionSetArn": "arn:aws:sso:::permissionSet/sso-instance-id/permission-set-id",
                    "Name": "MatchingPermissionSetName",
                }
            },
            "DescribeUser": {"UserName": "matchinguser@example.com"},
        }
        os.environ["PermissionSetNamePattern"] = "^MatchingPermissionSetName$"
        os.environ["PrincipalGroupNamePattern"] = "^MatchingGroupName$"
        os.environ["PrincipalUserNameEmail"] = "matchinguser@example.com"
        os.environ["Mode"] = "DISABLED"

        result = lambda_handler(event, None)
        self.assertEqual(result["result"], "SUCCESS")
        self.assertIn("DISABLED", result["message"])
        self.assertEqual(result["details"], {"mode": "DISABLED"})
        mock_client.delete_account_assignment.assert_not_called()

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_disabled_mode_short_circuits_before_event_parsing(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        # Defense-in-depth: DISABLED must be honoured on any payload, including
        # stripped-down direct invocations used to test the kill switch. The check
        # runs before any event field destructuring, so an empty event is fine.
        os.environ["Mode"] = "DISABLED"

        result = lambda_handler({}, None)
        self.assertEqual(result["result"], "SUCCESS")
        self.assertIn("DISABLED", result["message"])
        self.assertEqual(result["details"], {"mode": "DISABLED"})
        mock_client.delete_account_assignment.assert_not_called()

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_unknown_mode_fails_closed(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        # CloudFormation AllowedValues blocks typos at deploy time, but a direct
        # env-var override (or tooling bug) could land an unknown value. Must be
        # treated as DISABLED, not silently fall through to ENFORCE.
        os.environ["Mode"] = "ENORCE"

        result = lambda_handler({}, None)
        self.assertEqual(result["result"], "SUCCESS")
        self.assertIn("DISABLED", result["message"])
        self.assertEqual(result["details"], {"mode": "DISABLED"})
        mock_client.delete_account_assignment.assert_not_called()

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_dry_run_mode(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        event = {
            "DescribeInstance": {
                "InstanceArn": "arn:aws:sso:::instance/sso-instance-id"
            },
            "RequestParameters": {
                "targetId": "target-id",
                "targetType": "AWS_ACCOUNT",
                "principalType": "USER",
                "principalId": "user-id",
            },
            "DescribePermissionSet": {
                "PermissionSet": {
                    "PermissionSetArn": "arn:aws:sso:::permissionSet/sso-instance-id/permission-set-id",
                    "Name": "MatchingPermissionSetName",
                }
            },
            "DescribeUser": {"UserName": "matchinguser@example.com"},
        }
        os.environ["PermissionSetNamePattern"] = "^MatchingPermissionSetName$"
        os.environ["PrincipalGroupNamePattern"] = "^MatchingGroupName$"
        os.environ["PrincipalUserNameEmail"] = "matchinguser@example.com"
        os.environ["Mode"] = "DRY_RUN"

        result = lambda_handler(event, None)
        self.assertEqual(result["result"], "SUCCESS")
        self.assertIn("DRY_RUN", result["message"])
        self.assertEqual(result["details"], {"mode": "DRY_RUN"})
        mock_client.delete_account_assignment.assert_not_called()

    @patch("cerberus.src.cerberus.app.cloudwatch", new_callable=MagicMock)
    @patch("cerberus.src.cerberus.app.logger")
    @patch("cerberus.src.cerberus.app.client", new_callable=MagicMock)
    def test_lambda_handler_group_principal_match(
        self, mock_client, mock_logger, mock_cloudwatch
    ):
        event = {
            "DescribeInstance": {
                "InstanceArn": "arn:aws:sso:::instance/sso-instance-id"
            },
            "RequestParameters": {
                "targetId": "target-id",
                "targetType": "AWS_ACCOUNT",
                "principalType": "GROUP",
                "principalId": "group-id",
            },
            "DescribePermissionSet": {
                "PermissionSet": {
                    "PermissionSetArn": "arn:aws:sso:::permissionSet/sso-instance-id/permission-set-id",
                    "Name": "MatchingPermissionSetName",
                }
            },
            "DescribeGroup": {"DisplayName": "MatchingGroupName"},
        }
        os.environ["PermissionSetNamePattern"] = "^MatchingPermissionSetName$"
        os.environ["PrincipalGroupNamePattern"] = "^MatchingGroupName$"
        os.environ["PrincipalUserNameEmail"] = ""
        mock_client.delete_account_assignment.return_value = {
            "AccountAssignmentDeletionStatus": {
                "Status": "SUCCEEDED",
                "RequestId": "22222222-3333-4444-5555-666666666666",
            }
        }
        result = lambda_handler(event, None)
        self.assertEqual(result["result"], "SUCCESS")
        self.assertIn("SUCCEEDED", result["message"])
        self.assertIn("AccountAssignmentDeletionStatus", result["details"])
        mock_client.delete_account_assignment.assert_called_once()
