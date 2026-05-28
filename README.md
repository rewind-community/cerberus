# Cerberus

![Cerberus](/static/CerberusLogo.png)

AWS Control Tower's default behavior in managed mode is to assign baseline [IAM Identity Center Groups for AWS Control Tower](https://docs.aws.amazon.com/en_us/controltower/latest/userguide//sso-groups.html) to newly enrolled accounts. These group assignments are also reapplied when an account update is performed; for instance, when a new version of the landing zone is made available.

The default **IAM Identity Center Groups for AWS Control Tower** are rather permissive. For instance, the `AWSControlTowerAdmins` permission set assigns the `AWSAdministratorAccess` managed IAM policy to the IAM Role. This behavior goes against our policy of maintaining least privilege access to our AWS accounts.

We have created [Cerberus](https://www.britannica.com/topic/Cerberus) to monitor events from the `sso.amazonaws.com` service. Cerberus, often referred to as the hound of Hades, is a multi-headed dog that guards the gates of the underworld to prevent the dead from leaving, or in this case, prevent `CreateAccountAssignment` of unauthorized (unwanted) default permission sets to AWS Control Tower managed accounts.

## Deployment

Cerberus is a single [AWS SAM](https://docs.aws.amazon.com/serverless-application-model/) stack that must be deployed in the AWS Organization **management account**. IAM Identity Center enforces a service-level restriction that prevents a delegated administrator from removing assignments owned by the management account — see [cerberus/README.md](cerberus/README.md#why-this-runs-in-the-aws-organization-management-account) for the full explanation, pre-deploy security checklist, parameter reference, and migration path from the older delegated-admin topology.

The repository ships a top-level `Makefile` as the single entry point for build, test, and deploy — no remembered SAM CLI command sequences required.

```bash
make help                                            # List all available targets
make check                                           # Validate template + run unit tests
make deploy \
  NOTIFICATION_EMAIL=oncall@example.com \
  MODE=DRY_RUN                                       # First-time deploy in DRY_RUN
```

After observing `DRY_RUN: would remove ...` lines in the `/cerberus` log group for real `CreateAccountAssignment` events, re-run with `MODE=ENFORCE` (or omit — `ENFORCE` is the template default).

In CI, set `CI=true` to skip the interactive changeset confirmation that `cerberus/samconfig.toml` enables by default.

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository.
2. Create a feature branch.
3. Run `make check` locally — must pass before opening a PR.
4. Commit your changes.
5. Submit a pull request.

## Code Formatting

This project uses [black](https://black.readthedocs.io/) for code formatting. Run the following command to format your code:

```bash
black .
```

## License

This project is licensed under the [MIT License](LICENSE).
