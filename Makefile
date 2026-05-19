# Cerberus — wrapper around SAM CLI + unit tests.
# Single entry point for CI/CD so deploys and tests don't depend on remembered
# command sequences. Targets are self-documenting; run `make help`.

SAM_DIR      := cerberus
PYTHON       ?= python3
VENV         := $(SAM_DIR)/.venv
VENV_PY      := $(VENV)/bin/python
VENV_MARKER  := $(VENV)/.installed
REQUIREMENTS := $(SAM_DIR)/tests/requirements.txt
AWS_REGION   ?= ca-central-1

# Required for `make deploy`. No defaults — failing closed is intentional.
MANAGEMENT_ACCOUNT_ID ?=
NOTIFICATION_EMAIL    ?=

# Optional parameter overrides for `make deploy`. Unset => template defaults apply.
MODE                    ?=
PERMISSION_SET_PATTERN  ?=
PRINCIPAL_GROUP_PATTERN ?=
PRINCIPAL_USER_EMAIL    ?=
LOG_GROUP_NAME          ?=
LOG_GROUP_RETENTION     ?=

.DEFAULT_GOAL := help
.PHONY: help install validate test check build deploy clean _check-deploy-params

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

$(VENV_MARKER): $(REQUIREMENTS)
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -r $(REQUIREMENTS)
	@touch $(VENV_MARKER)

install: $(VENV_MARKER) ## Set up local venv with test dependencies

validate: ## Lint and validate the SAM template
	cd $(SAM_DIR) && sam validate --lint

test: $(VENV_MARKER) ## Run unit tests
	AWS_DEFAULT_REGION=$(AWS_REGION) $(VENV_PY) -m unittest discover -s $(SAM_DIR)/tests/unit -t . -v

check: validate test ## CI gate — validate + test

build: ## Build deployment artifacts (sam build)
	cd $(SAM_DIR) && sam build

deploy: _check-deploy-params build ## Deploy stack (requires MANAGEMENT_ACCOUNT_ID, NOTIFICATION_EMAIL)
	cd $(SAM_DIR) && sam deploy \
		$(if $(CI),--no-confirm-changeset) \
		--parameter-overrides \
			ManagementAccountId=$(MANAGEMENT_ACCOUNT_ID) \
			NotificationEmail=$(NOTIFICATION_EMAIL) \
			$(if $(MODE),Mode=$(MODE)) \
			$(if $(PERMISSION_SET_PATTERN),"PermissionSetNamePattern=$(PERMISSION_SET_PATTERN)") \
			$(if $(PRINCIPAL_GROUP_PATTERN),"PrincipalGroupNamePattern=$(PRINCIPAL_GROUP_PATTERN)") \
			$(if $(PRINCIPAL_USER_EMAIL),PrincipalUserNameEmail=$(PRINCIPAL_USER_EMAIL)) \
			$(if $(LOG_GROUP_NAME),LogGroupName=$(LOG_GROUP_NAME)) \
			$(if $(LOG_GROUP_RETENTION),LogGroupRetentionDays=$(LOG_GROUP_RETENTION))

clean: ## Remove build artifacts and venv
	rm -rf $(SAM_DIR)/.aws-sam $(VENV)

_check-deploy-params:
	@missing=0; \
	if [ -z "$(MANAGEMENT_ACCOUNT_ID)" ]; then echo "ERROR: MANAGEMENT_ACCOUNT_ID is required (12-digit AWS account ID)"; missing=1; fi; \
	if [ -z "$(NOTIFICATION_EMAIL)" ]; then echo "ERROR: NOTIFICATION_EMAIL is required"; missing=1; fi; \
	if [ $$missing -ne 0 ]; then \
		echo ""; \
		echo "Usage: make deploy MANAGEMENT_ACCOUNT_ID=123456789012 NOTIFICATION_EMAIL=ops@example.com"; \
		echo "Optional: MODE={ENFORCE|DRY_RUN|DISABLED} PERMISSION_SET_PATTERN='...' PRINCIPAL_GROUP_PATTERN='...' PRINCIPAL_USER_EMAIL='...' LOG_GROUP_NAME='/cerberus' LOG_GROUP_RETENTION=14"; \
		echo "In CI: set CI=true to skip the interactive changeset confirmation."; \
		exit 1; \
	fi
