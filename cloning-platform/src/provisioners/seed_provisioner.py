"""
seed_provisioner.py — Seeds the shared DynamoDB database with the initial tenant configuration and admin user.
"""
from __future__ import annotations

import re

from ..common.constants import ResourceType
from ..common.models import EnvironmentModel, ResourceRecord
from .base import BaseProvisioner

class SeedProvisioner(BaseProvisioner):
    """Injects initial tenant data into the shared database tables."""

    resource_type = ResourceType.SEED_DATA

    def _create(self, env: EnvironmentModel) -> ResourceRecord:
        ddb = self.get_source_client("dynamodb")

        org_id = f"org-{env.target_env_name}"
        admin_email = env.contact_email or f"admin@{env.target_env_name}.com"
        staff_id = self._build_staff_id(env.target_env_name)

        # Default logo — absolute S3 URL so Next.js <Image> and Assess can load it.
        # NEVER use a relative filename like "default-logo.png" — it will 404 in production.
        DEFAULT_LOGO = "https://alliancecaretech-public-resources.s3.amazonaws.com/Engage/act_banner_Group3.svg"

        # 1. Seed Organization Configuration
        config_table_name = "Catalyst_CompConfig"
        self.logger.info("Seeding Organization Config", extra={"table": config_table_name})
        try:
            ddb.put_item(
                TableName=config_table_name,
                Item={
                    'serialNumber': {'S': org_id},
                    'ambulanceNum': {'S': '998'},
                    'appColor': {'S': '#1f733d'},
                    # Both scan count fields must be present to avoid NaN in the Assess UI
                    'appDHAScanCount': {'S': '3'},
                    'assessDHAScanCount': {'S': '3'},
                    'appIsAssessAndPlan': {'BOOL': True},
                    # Use absolute S3 URLs — relative filenames like "default-logo.png" 404 in Next.js
                    'appLogo': {'S': DEFAULT_LOGO},
                    'appName': {'S': 'Engage'},
                    'appPhone': {'S': 'phone number'},
                    'assessColor': {'S': '#1f733d'},
                    'assessHeader': {'S': env.company_name},
                    'assessLogo': {'S': DEFAULT_LOGO},
                    'assessName': {'S': 'Assess'},
                    # assessPrefix is stored as plain text — backendApi uses it directly.
                    # Do NOT encrypt it here; crypto.js decryptMessage handles plaintext gracefully.
                    'assessPrefix': {'S': 'ACTI'},
                    'businessAddress': {'S': ''},
                    'country': {'S': 'UAE'},
                    'email': {'S': ''},
                    'facilityName': {'S': ''},
                    'fireFighterNum': {'S': '997'},
                    'fontSize': {'S': '0'},
                    'globalDay': {'S': '1'},
                    'isAppBloodPresure': {'BOOL': True},
                    'isAppBody': {'BOOL': True},
                    'isAppCalories': {'BOOL': True},
                    'isAppDHAScan': {'BOOL': True},
                    'isAppFeeling': {'BOOL': True},
                    'isAppHeartRhythmScan': {'BOOL': True},
                    'isAppMessages': {'BOOL': True},
                    'isAppMoreState': {'BOOL': True},
                    'isAppOxygenSaturation': {'BOOL': True},
                    'isAppRespiratoryRate': {'BOOL': True},
                    'isAppSleep': {'BOOL': True},
                    'isAppStep': {'BOOL': True},
                    'isAppVital': {'BOOL': True},
                    'isAssess3d': {'BOOL': True},
                    'isAssessBiometric': {'BOOL': True},
                    'isAssessCognitive': {'BOOL': True},
                    'isAssessLearnBtn': {'BOOL': True},
                    'isAssessRatina': {'BOOL': True},
                    'isAssessSelfAssessment': {'BOOL': True},
                    'isOthers': {'BOOL': True},
                    'isPurchaseScreen': {'BOOL': True},
                    'lang': {'S': 'en'},
                    'messageAppBackgroundColor': {'S': '#00a9ce8C'},
                    'organizationName': {'S': org_id},
                    'partnerName': {'S': ''},
                    'phone': {'S': 'phone number'},
                    'policeNum': {'S': '999'},
                    'solution': {'S': 'Full-Solution'},
                    'staffColor': {'S': '#1f733d'},
                    'staffHeader': {'S': env.company_name},
                    # Use absolute S3 URL for staffLogo — relative paths 404 in Next.js <Image>
                    'staffLogo': {'S': DEFAULT_LOGO},
                    'staffName': {'S': ''},
                    'termsOfUse': {'S': 'Sample'},
                    'theme': {'S': 'solidGreen'},
                    'environment': {'S': env.target_env_name},
                    'organizationId': {'S': org_id}
                }
            )
        except Exception as e:
            self.logger.error("Failed to seed Configuration", exc_info=e)
            raise e

        # 2. Seed Admin Staff
        staff_table_name = "catEncounter_StaffTable"
        self.logger.info("Seeding Admin Staff", extra={"table": staff_table_name})
        try:
            ddb.put_item(
                TableName=staff_table_name,
                Item={
                    'staffId': {'S': staff_id},
                    'organizationId': {'S': org_id},
                    's_EmailId': {'S': admin_email},
                    's_FirstName': {'S': 'Admin'},
                    's_LastName': {'S': 'User'},
                    'role': {'S': 'eng_acc_gr_7_super_admin'},
                    's_Theme': {'S': '#117D70'}
                }
            )
        except Exception as e:
            self.logger.error("Failed to seed Staff", exc_info=e)
            raise e

        # 3. Seed initial Thought of the Day to prevent "data is undefined" runtime errors
        self._seed_thought_of_day(ddb, org_id)

        return ResourceRecord(
            resource_type=self.resource_type,
            source_id=env.source_env_name,
            target_id="shared-database-seeded",
            target_arn="",
            metadata={"seeded": True, "org_id": org_id, "admin": admin_email},
        )

    def _seed_thought_of_day(self, ddb: object, org_id: str) -> None:
        """Seed an initial Thought of the Day so the widget never returns undefined."""
        thought_table = "Thought_Table"
        # serialNumber is the primary key of Thought_Table; use a deterministic value
        serial = f"thought-{org_id}"
        try:
            ddb.put_item(
                TableName=thought_table,
                Item={
                    'serialNumber': {'S': serial},
                    'organizationId': {'S': org_id},
                    'thoughtOfDay': {'S': 'Welcome to your wellness journey! Start today with a small step toward a healthier life.'},
                    'organizationName': {'S': org_id},
                },
                # Only insert if this serialNumber does not exist yet (idempotent)
                ConditionExpression='attribute_not_exists(serialNumber)',
            )
            self.logger.info("Seeded initial Thought of the Day", extra={"org": org_id, "serial": serial})
        except Exception:
            # ConditionalCheckFailedException means a thought already exists — that's fine
            self.logger.info("Thought_Table entry already exists, skipping", extra={"org": org_id})

    def validate(self, record: ResourceRecord) -> bool:
        return True

    def _build_staff_id(self, env_name: str) -> str:
        normalized = re.sub(r"[^A-Z0-9]", "", env_name.upper())
        return f"{normalized[:12] or 'TENANT'}-ADMIN"
