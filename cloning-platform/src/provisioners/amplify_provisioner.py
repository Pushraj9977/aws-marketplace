"""
amplify_provisioner.py — Clone an Amplify branch for the new tenant environment.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import boto3

from ..common.constants import ResourceType
from ..common.models import EnvironmentModel, ResourceRecord
from ..common.utils import retry
from .base import BaseProvisioner


class AmplifyProvisioner(BaseProvisioner):
    """Creates a new Amplify branch for the target environment and triggers deployment."""

    resource_type = ResourceType.AMPLIFY_BRANCH

    def _create(self, env: EnvironmentModel) -> ResourceRecord:
        amp = self.get_client("amplify")
        app_id = env.amplify_app_id
        branch_name = env.target_env_name

        if not app_id:
            self.logger.warning("No Amplify App ID configured — skipping Amplify branch")
            return ResourceRecord(
                resource_type=self.resource_type,
                source_id=env.source_env_name,
                target_id="",
                metadata={"message": "Skipped — no amplify_app_id configured"},
            )

        # Idempotency
        if self._branch_exists(amp, app_id, branch_name):
            self.logger.warning(
                "Amplify branch already exists — skipping",
                extra={"branch": branch_name},
            )
            return ResourceRecord(
                resource_type=self.resource_type,
                source_id=env.source_env_name,
                target_id=branch_name,
                metadata={"skipped": True},
            )

        # Build environment variable string
        env_vars = self._build_env_vars(env)
        
        # Automatically create GitHub branch so Amplify doesn't fail on git clone
        self._create_github_branch(branch_name, source_branch="test")
        
        branch = self._create_branch(amp, app_id, branch_name, env_vars, env)

        # Trigger deployment
        self._trigger_deployment(amp, app_id, branch_name)

        return ResourceRecord(
            resource_type=self.resource_type,
            source_id=env.source_env_name,
            target_id=branch_name,
            target_arn=branch.get("branchArn", ""),
            metadata={"app_id": app_id, "env_vars": env_vars},
        )

    def _branch_exists(self, amp: object, app_id: str, branch_name: str) -> bool:
        try:
            amp.get_branch(appId=app_id, branchName=branch_name)  # type: ignore[attr-defined]
            return True
        except amp.exceptions.NotFoundException:  # type: ignore[attr-defined]
            return False
        except Exception:
            return False

    def _build_env_vars(self, env: EnvironmentModel) -> dict[str, str]:
        vars_: dict[str, str] = {
            "ENV_NAME": env.target_env_name,
            "USER_POOL_ID": env.user_pool_id,
            "APP_CLIENT_ID": env.app_client_id,
            "SECRET_NAME": env.secret_name,
            "REGION": self.region,
        }
        # Inject all API URLs
        for fn_name, url in env.api_urls.items():
            key = f"NEXT_PUBLIC_{fn_name.upper().replace('-', '_')}_URL"
            vars_[key] = url
        return vars_

    @retry(max_attempts=3, delay_seconds=3.0)
    def _create_branch(
        self,
        amp: object,
        app_id: str,
        branch_name: str,
        env_vars: dict[str, str],
        env: EnvironmentModel,
    ) -> dict:
        import base64

        # api_urls keys are full function names like "backendApi-final-test-seven"
        # Strip the env suffix to get the base name for lookup
        def get_api_url(base_name: str) -> str:
            # Try exact match first
            if base_name in env.api_urls:
                return env.api_urls[base_name]
            # Try with env suffix
            full_name = f"{base_name}-{env.target_env_name}"
            if full_name in env.api_urls:
                return env.api_urls[full_name]
            # Try prefix match
            for key, url in env.api_urls.items():
                if key.startswith(base_name):
                    return url
            return ""

        backend_url = get_api_url("backendApi")
        staff_url = get_api_url("staffApi")
        engage_url = get_api_url("engageapi")
        bha_url = get_api_url("bhaSession")
        webhook_url = get_api_url("webhook")

        aws_exports_content = f"""const awsmobile = {{
    "aws_project_region": "{self.region}",
    "aws_cloud_logic_custom": [
        {{ "name": "backendApi", "endpoint": "{backend_url}", "region": "{self.region}" }},
        {{ "name": "staffApi", "endpoint": "{staff_url}", "region": "{self.region}" }},
        {{ "name": "engageapi", "endpoint": "{engage_url}", "region": "{self.region}" }},
        {{ "name": "bhaSession", "endpoint": "{bha_url}", "region": "{self.region}" }},
        {{ "name": "webhook", "endpoint": "{webhook_url}", "region": "{self.region}" }}
    ],
    "aws_appsync_graphqlEndpoint": "{env.appsync_graphql_url or 'https://placeholder/graphql'}",
    "aws_appsync_region": "{self.region}",
    "aws_appsync_authenticationType": "API_KEY",
    "aws_appsync_apiKey": "{env.appsync_api_key}",
    "aws_cognito_identity_pool_id": "{env.identity_pool_id}",
    "aws_cognito_region": "{self.region}",
    "aws_user_pools_id": "{env.user_pool_id}",
    "aws_user_pools_web_client_id": "{env.app_client_id}",
    "oauth": {{}},
    "aws_cognito_username_attributes": ["EMAIL"],
    "aws_cognito_social_providers": [],
    "aws_cognito_signup_attributes": ["EMAIL"],
    "aws_cognito_mfa_configuration": "OFF",
    "aws_cognito_mfa_types": ["SMS"],
    "aws_cognito_password_protection_settings": {{
        "passwordPolicyMinLength": 8,
        "passwordPolicyCharacters": []
    }},
    "aws_cognito_verification_mechanisms": ["EMAIL"]
}};
export default awsmobile;
"""
        
        # Create GitHub branch first so Amplify has a target to clone
        self._create_github_branch(env.target_env_name)
        
        # Commit custom aws-exports.js directly to the newly created branch
        self._commit_aws_exports_to_github(env.target_env_name, aws_exports_content)
        
        resp = amp.create_branch(  # type: ignore[attr-defined]
            appId=app_id,
            branchName=branch_name,
            stage="DEVELOPMENT",
            framework="Next.js - SSR",
            environmentVariables=env_vars,
            tags={
                "Environment": env.target_env_name,
                "ManagedBy": "CloningPlatform",
            },
        )
        self.logger.info(
            "Amplify branch created and mapped to GitHub",
            extra={"branch": branch_name, "app_id": app_id},
        )
        return resp.get("branch", {})

    def _get_github_token(self) -> str:
        sm = boto3.client("secretsmanager", region_name=self.region)
        try:
            resp = sm.get_secret_value(SecretId="cloning-platform/github-token")
            return resp.get("SecretString", "")
        except Exception as e:
            self.logger.warning(f"Failed to retrieve GitHub token: {e}")
            return ""

    def _create_github_branch(self, target_branch: str, source_branch: str = "test") -> None:
        token = self._get_github_token()
        if not token:
            self.logger.warning("No GitHub token available, skipping GitHub branch creation")
            return
            
        owner = "ACT-INTL"
        repo = "Catalyst-HealthyAging"
        
        try:
            # 1. Get the SHA of the source branch
            url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{source_branch}"
            req = urllib.request.Request(url, headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json"
            })
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                sha = data["object"]["sha"]
                
            # 2. Create the new branch pointing to that SHA
            create_url = f"https://api.github.com/repos/{owner}/{repo}/git/refs"
            payload = json.dumps({
                "ref": f"refs/heads/{target_branch}",
                "sha": sha
            }).encode("utf-8")
            
            create_req = urllib.request.Request(create_url, data=payload, headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json"
            }, method="POST")
            
            with urllib.request.urlopen(create_req):
                self.logger.info(f"Successfully created GitHub branch {target_branch} from {source_branch}")
                
        except urllib.error.HTTPError as e:
            if e.code == 422: # Reference already exists
                self.logger.info(f"GitHub branch {target_branch} already exists, proceeding")
            else:
                body = e.read().decode() if hasattr(e, 'read') else str(e)
                self.logger.warning(f"GitHub API error: {e.code} - {body}")
        except Exception as e:
            self.logger.warning(f"Failed to create GitHub branch: {e}")

    def _commit_aws_exports_to_github(self, target_branch: str, content: str) -> None:
        token = self._get_github_token()
        if not token:
            return
            
        owner = "ACT-INTL"
        repo = "Catalyst-HealthyAging"
        path = "src/aws-exports.js"
        
        # 1. Get file SHA to update it
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={target_branch}"
            req = urllib.request.Request(url, headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json"
            })
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                file_sha = data["sha"]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                file_sha = None
            else:
                self.logger.warning(f"Failed to get aws-exports.js SHA: {e}")
                return
                
        # 2. Update/Create the file
        update_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        import base64
        payload_dict = {
            "message": "Auto-inject custom aws-exports.js for environment",
            "content": base64.b64encode(content.encode('utf-8')).decode('utf-8'),
            "branch": target_branch
        }
        if file_sha:
            payload_dict["sha"] = file_sha
            
        payload = json.dumps(payload_dict).encode("utf-8")
        
        try:
            update_req = urllib.request.Request(update_url, data=payload, headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json"
            }, method="PUT")
            with urllib.request.urlopen(update_req) as response:
                self.logger.info(f"Successfully committed aws-exports.js to GitHub branch {target_branch}")
        except Exception as e:
            self.logger.warning(f"Failed to commit aws-exports.js: {e}")


    def _trigger_deployment(self, amp: object, app_id: str, branch_name: str) -> None:
        try:
            amp.start_job(  # type: ignore[attr-defined]
                appId=app_id, branchName=branch_name, jobType="RELEASE"
            )
            self.logger.info(
                "Amplify RELEASE deployment triggered",
                extra={"branch": branch_name},
            )
        except Exception as exc:
            self.logger.warning(
                "Could not trigger Amplify deployment — connect GitHub branch manually",
                extra={"error": str(exc)},
            )

    def validate(self, record: ResourceRecord) -> bool:
        if not record.target_id or record.metadata.get("skipped"):
            return True
        amp = self.get_client("amplify")
        app_id = record.metadata.get("app_id", "")
        if not app_id:
            return True
        try:
            amp.get_branch(appId=app_id, branchName=record.target_id)
            return True
        except Exception:
            return False
