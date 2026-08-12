"""
cognito_provisioner.py — Clone Cognito User Pool + App Client for a new tenant.
"""
from __future__ import annotations

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
        admin_email, admin_password = self._create_admin_user(idp, pool_id, env)
        env.admin_email = admin_email
        env.admin_password = admin_password

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
                "admin_password": admin_password,
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
            )
            client_id: str = resp["UserPoolClient"]["ClientId"]
            self.logger.info("App Client created", extra={"client_id": client_id})
            return client_id
        except Exception:
            # If creation fails, fetch existing client
            clients = idp.list_user_pool_clients(  # type: ignore[attr-defined]
                UserPoolId=pool_id, MaxResults=10
            )
            if clients.get("UserPoolClients"):
                return clients["UserPoolClients"][0]["ClientId"]
            raise

    @retry(max_attempts=3, delay_seconds=2.0)
    def _create_admin_user(self, idp: object, pool_id: str, env: EnvironmentModel) -> tuple[str, str]:
        """Create a default admin user with a permanent password."""
        email = f"admin@{env.target_env_name}.com"
        password = "@~W@a27Z"  # Minimum 8, Upper, Lower, Number

        try:
            # 1. Create the user
            idp.admin_create_user(  # type: ignore[attr-defined]
                UserPoolId=pool_id,
                Username=email,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"}
                ],
                MessageAction="SUPPRESS"
            )
            
            # 2. Set permanent password
            idp.admin_set_user_password(  # type: ignore[attr-defined]
                UserPoolId=pool_id,
                Username=email,
                Password=password,
                Permanent=True
            )
            
            self.logger.info("Default admin user created", extra={"email": email})
        except idp.exceptions.UsernameExistsException:  # type: ignore[attr-defined]
            self.logger.warning("Admin user already exists", extra={"email": email})
            
        return email, password

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

    def validate(self, record: ResourceRecord) -> bool:
        idp = self.get_client("cognito-idp")
        try:
            idp.describe_user_pool(UserPoolId=record.target_id)
            return True
        except Exception as e:
            self.logger.error("Cognito validation error", extra={"error": str(e), "pool_id": record.target_id})
            return False
