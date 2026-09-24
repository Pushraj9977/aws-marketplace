"""
cognito_provisioner.py — Clone Cognito User Pool + App Client for a new tenant.
"""
from __future__ import annotations

import json
import os
import secrets
import string

from ..common.constants import ResourceType
from ..common.models import EnvironmentModel, ResourceRecord
from ..common.utils import retry
from .base import BaseProvisioner


class CognitoProvisioner(BaseProvisioner):
    """Creates a new Cognito User Pool and App Client for the target environment."""

    resource_type = ResourceType.COGNITO_USER_POOL

    def _create(self, env: EnvironmentModel) -> ResourceRecord:
        idp = self.get_client("cognito-idp")
        pool_name = f"{env.target_env_name}-userpool"
        client_name = f"{env.target_env_name}-client"

        # Idempotency: check if pool already exists
        pool_id = self._find_existing_pool(idp, pool_name)
        if pool_id:
            self.logger.warning(
                "User pool already exists, reusing", extra={"pool_id": pool_id}
            )
        else:
            pool_id = self._create_pool(idp, pool_name, env)

        # Create App Client (always attempt — check handles duplicate)
        app_client_id = self._create_client(idp, pool_id, client_name)

        # Inject into env model for downstream provisioners
        env.user_pool_id = pool_id
        env.app_client_id = app_client_id

        # Create Admin User
        sm = self.get_client("secretsmanager")
        admin_email, admin_password, credentials_secret_name = self._create_admin_user(
            idp,
            sm,
            pool_id,
            env,
        )
        env.admin_email = admin_email
        env.admin_password = admin_password
        env.admin_credentials_secret_name = credentials_secret_name

        # Create Identity Pool
        id_pool_id = self._create_identity_pool(idp, pool_id, app_client_id, pool_name, env)
        env.identity_pool_id = id_pool_id

        return ResourceRecord(
            resource_type=self.resource_type,
            source_id=env.source_env_name,
            target_id=pool_id,
            target_arn=f"arn:aws:cognito-idp:{self.region}:{self.account_id}:userpool/{pool_id}",
            metadata={
                "app_client_id": app_client_id,
                "pool_name": pool_name,
                "admin_email": admin_email,
                "admin_credentials_secret_name": credentials_secret_name,
                "identity_pool_id": id_pool_id,
            },
        )

    def _find_existing_pool(self, idp: object, pool_name: str) -> str:
        """Return existing pool ID if found, else empty string."""
        resp = idp.list_user_pools(MaxResults=60)  # type: ignore[attr-defined]
        for pool in resp.get("UserPools", []):
            if pool["Name"] == pool_name:
                return pool["Id"]
        return ""

    @retry(max_attempts=3, delay_seconds=3.0)
    def _create_pool(self, idp: object, pool_name: str, env: EnvironmentModel) -> str:
        # SES ARN for production email sending (avoids Cognito default 50/day limit)
        ses_source_arn = os.environ.get(
            "SES_SOURCE_ARN",
            "arn:aws:ses:eu-central-1:215116348101:identity/act1@alliancecaretech.com",
        )
        ses_from_email = os.environ.get("SES_FROM_EMAIL", "act1@alliancecaretech.com")

        resp = idp.create_user_pool(  # type: ignore[attr-defined]
            PoolName=pool_name,
            AutoVerifiedAttributes=["email"],
            UsernameAttributes=["email"],
            MfaConfiguration="OFF",
            Policies={
                "PasswordPolicy": {
                    "MinimumLength": 8,
                    "RequireUppercase": True,
                    "RequireLowercase": True,
                    "RequireNumbers": True,
                    "RequireSymbols": False,
                }
            },
            # Use SES for reliable email delivery (no 50/day sandbox limit)
            EmailConfiguration={
                "EmailSendingAccount": "DEVELOPER",
                "SourceArn": ses_source_arn,
                "From": ses_from_email,
            },
            # Custom attributes required by the Assess React frontend (Signup.tsx)
            # Auth.signUp sends: custom:firstName, custom:lastName, custom:phone
            Schema=[
                {
                    "Name": "firstName",
                    "AttributeDataType": "String",
                    "Mutable": True,
                    "StringAttributeConstraints": {"MinLength": "0", "MaxLength": "256"},
                },
                {
                    "Name": "lastName",
                    "AttributeDataType": "String",
                    "Mutable": True,
                    "StringAttributeConstraints": {"MinLength": "0", "MaxLength": "256"},
                },
                {
                    "Name": "phone",
                    "AttributeDataType": "String",
                    "Mutable": True,
                    "StringAttributeConstraints": {"MinLength": "0", "MaxLength": "32"},
                },
            ],
            UserPoolTags={
                "Environment": env.target_env_name,
                "ManagedBy": "CloningPlatform",
            },
        )
        pool_id: str = resp["UserPool"]["Id"]
        self.logger.info("Cognito User Pool created", extra={"pool_id": pool_id})
        return pool_id

    @retry(max_attempts=3, delay_seconds=2.0)
    def _create_client(self, idp: object, pool_id: str, client_name: str) -> str:
        """Create an App Client with no secret (SPA-compatible)."""
        try:
            resp = idp.create_user_pool_client(  # type: ignore[attr-defined]
                UserPoolId=pool_id,
                ClientName=client_name,
                GenerateSecret=False,
                ExplicitAuthFlows=[
                    "ALLOW_USER_PASSWORD_AUTH",
                    "ALLOW_REFRESH_TOKEN_AUTH",
                    "ALLOW_USER_SRP_AUTH",
                    "ALLOW_ADMIN_USER_PASSWORD_AUTH",
                ],
                # Required: custom attributes must be explicitly listed for R/W
                # The Assess frontend (Signup.tsx) writes: custom:firstName, custom:lastName, custom:phone
                WriteAttributes=[
                    "email", "given_name", "family_name", "name", "phone_number",
                    "custom:firstName", "custom:lastName", "custom:phone",
                ],
                ReadAttributes=[
                    "email", "given_name", "family_name", "name", "phone_number", "sub",
                    "custom:firstName", "custom:lastName", "custom:phone",
                ],
            )
            client_id: str = resp["UserPoolClient"]["ClientId"]
            self.logger.info("App Client created", extra={"client_id": client_id})
            return client_id
        except Exception:
            existing_client_id = self._find_existing_client(idp, pool_id, client_name)
            if existing_client_id:
                return existing_client_id
            raise

    @retry(max_attempts=3, delay_seconds=2.0)
    def _create_admin_user(
        self,
        idp: object,
        sm: object,
        pool_id: str,
        env: EnvironmentModel,
    ) -> tuple[str, str, str]:
        """Create a default admin user with a permanent password."""
        email = env.contact_email or f"admin@{env.target_env_name}.com"
        credentials_secret_name = f"{env.target_env_name}/admin-bootstrap"
        password = self._get_admin_password(sm, credentials_secret_name)

        try:
            resp = idp.admin_create_user(  # type: ignore[attr-defined]
                UserPoolId=pool_id,
                Username=email,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"}
                ],
                MessageAction="SUPPRESS"
            )
            user_attrs = resp.get("User", {}).get("Attributes", [])
            self.logger.info("Default admin user created", extra={"email": email})
        except idp.exceptions.UsernameExistsException:  # type: ignore[attr-defined]
            resp = idp.admin_get_user(UserPoolId=pool_id, Username=email)  # type: ignore[attr-defined]
            user_attrs = resp.get("UserAttributes", [])
            self.logger.warning("Admin user already exists", extra={"email": email})

        # Extract the Cognito sub UUID and update DynamoDB so the frontend staffApi can find the user
        sub_uuid = next((attr["Value"] for attr in user_attrs if attr["Name"] == "sub"), None)
        if sub_uuid:
            self._link_dynamodb_user(env, sub_uuid)

        idp.admin_set_user_password(  # type: ignore[attr-defined]
            UserPoolId=pool_id,
            Username=email,
            Password=password,
            Permanent=True,
        )
        self._store_admin_credentials(sm, credentials_secret_name, email, password, env)
        return email, password, credentials_secret_name

    def _link_dynamodb_user(self, env: EnvironmentModel, sub_uuid: str) -> None:
        import re
        normalized = re.sub(r"[^A-Z0-9]", "", env.target_env_name.upper())
        staff_id = f"{normalized[:12] or 'TENANT'}-ADMIN"
        try:
            ddb = self.get_client("dynamodb")
            ddb.update_item(
                TableName="catEncounter_StaffTable",
                Key={"staffId": {"S": staff_id}},
                UpdateExpression="SET user_id = :u",
                ExpressionAttributeValues={":u": {"S": sub_uuid}},
            )
        except Exception as e:
            self.logger.error("Failed to link DynamoDB user", exc_info=e)

    @retry(max_attempts=3, delay_seconds=2.0)
    def _create_identity_pool(self, idp: object, user_pool_id: str, app_client_id: str, pool_name: str, env: EnvironmentModel) -> str:
        """Create a Cognito Identity Pool linked to the new User Pool."""
        client = self.get_client("cognito-identity")
        identity_pool_name = pool_name.replace("-", "_")  # Identity pools use underscores often

        # Check if exists
        try:
            pools = client.list_identity_pools(MaxResults=60)  # type: ignore[attr-defined]
            for p in pools.get("IdentityPools", []):
                if p["IdentityPoolName"] == identity_pool_name:
                    self.logger.info("Identity pool already exists", extra={"identity_pool_id": p["IdentityPoolId"]})
                    return p["IdentityPoolId"]
        except Exception as e:
            self.logger.warning(f"Error checking identity pools: {e}")

        # Create new
        self.logger.info("Creating new identity pool", extra={"identity_pool_name": identity_pool_name})
        provider_name = f"cognito-idp.{self.region}.amazonaws.com/{user_pool_id}"
        
        response = client.create_identity_pool(  # type: ignore[attr-defined]
            IdentityPoolName=identity_pool_name,
            AllowUnauthenticatedIdentities=True,  # Common in Amplify apps, adjust if needed
            CognitoIdentityProviders=[
                {
                    "ProviderName": provider_name,
                    "ClientId": app_client_id,
                    "ServerSideTokenCheck": False,
                }
            ]
        )
        pool_id = response["IdentityPoolId"]
        self.logger.info("Identity pool created", extra={"identity_pool_id": pool_id})
        
        self._setup_identity_pool_roles(env, pool_id)
        return pool_id

    @retry(max_attempts=3, delay_seconds=2.0)
    def _setup_identity_pool_roles(self, env: EnvironmentModel, pool_id: str) -> None:
        """Create IAM roles and attach them to the Identity Pool."""
        iam = self.get_client("iam")
        cognito_id = self.get_client("cognito-identity")
        
        import json
        
        def create_role(role_type: str) -> str:
            role_name = f"amplify-{env.target_env_name}-{role_type}Role"
            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Federated": "cognito-identity.amazonaws.com"},
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Condition": {
                        "StringEquals": {"cognito-identity.amazonaws.com:aud": pool_id},
                        "ForAnyValue:StringLike": {"cognito-identity.amazonaws.com:amr": role_type}
                    }
                }]
            }
            try:
                resp = iam.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy)
                )
                self.logger.info(f"Created {role_type} role", extra={"role_name": role_name})
                return resp["Role"]["Arn"]
            except iam.exceptions.EntityAlreadyExistsException:
                resp = iam.get_role(RoleName=role_name)
                self.logger.info(f"Reusing existing {role_type} role", extra={"role_name": role_name})
                
                # Update trust policy just in case the pool ID changed
                iam.update_assume_role_policy(
                    RoleName=role_name,
                    PolicyDocument=json.dumps(trust_policy)
                )
                return resp["Role"]["Arn"]
                
        auth_role_arn = create_role("authenticated")
        unauth_role_arn = create_role("unauthenticated")
        
        try:
            cognito_id.set_identity_pool_roles(
                IdentityPoolId=pool_id,
                Roles={
                    "authenticated": auth_role_arn,
                    "unauthenticated": unauth_role_arn
                }
            )
            self.logger.info("Attached IAM roles to identity pool", extra={"identity_pool_id": pool_id})
        except Exception as e:
            self.logger.warning(f"Failed to set identity pool roles: {e}")

    def _find_existing_client(self, idp: object, pool_id: str, client_name: str) -> str:
        clients = idp.list_user_pool_clients(  # type: ignore[attr-defined]
            UserPoolId=pool_id,
            MaxResults=60,
        )
        for client in clients.get("UserPoolClients", []):
            if client["ClientName"] == client_name:
                return client["ClientId"]
        if clients.get("UserPoolClients"):
            return clients["UserPoolClients"][0]["ClientId"]
        return ""

    def _get_admin_password(self, sm: object, secret_name: str) -> str:
        try:
            existing = sm.get_secret_value(SecretId=secret_name)  # type: ignore[attr-defined]
            payload = json.loads(existing.get("SecretString", "{}"))
            password = payload.get("admin_password")
            if password:
                return str(password)
        except Exception:
            pass

        configured = os.environ.get("DEFAULT_ADMIN_PASSWORD", "").strip()
        if configured:
            return configured
        return self._generate_password()

    def _generate_password(self, length: int = 16) -> str:
        alphabet = string.ascii_letters + string.digits
        password = [
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.digits),
            secrets.choice("!@#$%^&*"),
        ]
        password.extend(secrets.choice(alphabet) for _ in range(max(length - len(password), 8)))
        secrets.SystemRandom().shuffle(password)
        return "".join(password)

    def _store_admin_credentials(
        self,
        sm: object,
        secret_name: str,
        email: str,
        password: str,
        env: EnvironmentModel,
    ) -> None:
        payload = json.dumps({
            "admin_email": email,
            "admin_password": password,
            "user_pool_id": env.user_pool_id,
            "app_client_id": env.app_client_id,
        })
        try:
            sm.create_secret(  # type: ignore[attr-defined]
                Name=secret_name,
                Description=f"Bootstrap admin credentials for {env.target_env_name}",
                SecretString=payload,
                Tags=[
                    {"Key": "Environment", "Value": env.target_env_name},
                    {"Key": "ManagedBy", "Value": "CloningPlatform"},
                ],
            )
        except sm.exceptions.ResourceExistsException:  # type: ignore[attr-defined]
            sm.put_secret_value(SecretId=secret_name, SecretString=payload)  # type: ignore[attr-defined]

    def validate(self, record: ResourceRecord) -> bool:
        idp = self.get_client("cognito-idp")
        try:
            idp.describe_user_pool(UserPoolId=record.target_id)
            return True
        except Exception as e:
            self.logger.error("Cognito validation error", extra={"error": str(e), "pool_id": record.target_id})
            return False
