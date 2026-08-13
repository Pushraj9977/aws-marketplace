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
        ddb = self.get_client("dynamodb")

        org_id = f"org-{env.target_env_name}"
        admin_email = env.contact_email or f"admin@{env.target_env_name}.com"
        staff_id = self._build_staff_id(env.target_env_name)

        # 1. Seed Organization Configuration
        config_table_name = "Catalyst_CompConfig"
        self.logger.info("Seeding Organization Config", extra={"table": config_table_name})
        try:
            ddb.put_item(
                TableName=config_table_name,
                Item={
                    'serialNumber': {'S': org_id},
                    'organizationId': {'S': org_id},
                    'isAppCalories': {'BOOL': False},
                    'isAppMessages': {'BOOL': True},
                    'appColor': {'S': '#1f733d'},
                    'assessDHAScanCount': {'S': '3'},
                    'appDHAScanCount': {'S': '3'},
                    'environment': {'S': env.target_env_name},
                    'logoName': {'S': 'default-logo.png'},
                    'isAssess3d': {'BOOL': True}
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
                    's_Theme': {'S': 'dark'}
                }
            )
        except Exception as e:
            self.logger.error("Failed to seed Staff", exc_info=e)
            raise e

        return ResourceRecord(
            resource_type=self.resource_type,
            source_id=env.source_env_name,
            target_id="shared-database-seeded",
            target_arn="",
            metadata={"seeded": True, "org_id": org_id, "admin": admin_email},
        )

    def validate(self, record: ResourceRecord) -> bool:
        return True

    def _build_staff_id(self, env_name: str) -> str:
        normalized = re.sub(r"[^A-Z0-9]", "", env_name.upper())
        return f"{normalized[:12] or 'TENANT'}-ADMIN"
