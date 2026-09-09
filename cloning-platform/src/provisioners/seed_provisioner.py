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
                    'ambulanceNum': {'S': '998'},
                    'appColor': {'S': '#117D70'},
                    'appDHAScanCount': {'S': '3'},
                    'appIsAssessAndPlan': {'BOOL': True},
                    'appLogo': {'S': 'https://5thcolor.wordpress.com/wp-content/uploads/2011/10/logo-here.jpg'},
                    'appName': {'S': 'Engage'},
                    'appPhone': {'S': 'phone number'},
                    'assessColor': {'S': '#117D70'},
                    'assessHeader': {'S': env.company_name},
                    'assessLogo': {'S': 'https://5thcolor.wordpress.com/wp-content/uploads/2011/10/logo-here.jpg'},
                    'assessName': {'S': 'Assess'},
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
                    'organizationName': {'S': f"catalyst-assess-{env.target_env_name}"},
                    'partnerName': {'S': ''},
                    'phone': {'S': 'phone number'},
                    'policeNum': {'S': '999'},
                    'solution': {'S': 'Full-Solution'},
                    'staffColor': {'S': '#117D70'},
                    'staffHeader': {'S': env.company_name},
                    'staffLogo': {'S': 'https://5thcolor.wordpress.com/wp-content/uploads/2011/10/logo-here.jpg'},
                    'staffName': {'S': ''},
                    'termsOfUse': {'S': 'Sample'},
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
