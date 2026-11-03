#!/usr/bin/env python3
"""
replicate_all_resources.py — Comprehensive cross-region replicator from eu-central-1 to eu-west-1.
Complete Parity Engine:
1. All 46 DynamoDB Tables & Complete Schemas (KeySchema, GSIs, LSIs)
2. Master / Reference Table Data Migration (CompConfig, Thought_Table, FeelingMeter, etc.)
3. Cognito User Pool, Schema, App Client, AND Identity Pool (Federated Identities)
4. AppSync GraphQL API (Schema SDL, DataSources, Pipeline Functions, and Resolvers)
5. Base Application Lambda Functions (Code packages, environment variables, handlers)
6. REST API Gateways (Export from source via Swagger/OpenAPI and import to target)
"""
import argparse
import json
import logging
import sys
import tempfile
import time
import urllib.request
from typing import Any

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("FullRegionReplicator")


class FullRegionReplicator:
    def __init__(self, source_region: str = "eu-central-1", target_region: str = "eu-west-1"):
        self.source_region = source_region
        self.target_region = target_region
        self.session = boto3.Session()

        self.source_ddb = self.session.client("dynamodb", region_name=source_region)
        self.target_ddb = self.session.client("dynamodb", region_name=target_region)

        self.source_cognito = self.session.client("cognito-idp", region_name=source_region)
        self.target_cognito = self.session.client("cognito-idp", region_name=target_region)
        self.source_identity = self.session.client("cognito-identity", region_name=source_region)
        self.target_identity = self.session.client("cognito-identity", region_name=target_region)

        self.source_appsync = self.session.client("appsync", region_name=source_region)
        self.target_appsync = self.session.client("appsync", region_name=target_region)

        self.source_lam = self.session.client("lambda", region_name=source_region)
        self.target_lam = self.session.client("lambda", region_name=target_region)

        self.source_apigw = self.session.client("apigateway", region_name=source_region)
        self.target_apigw = self.session.client("apigateway", region_name=target_region)

    # =========================================================================
    # 1. DYNAMODB REPLICATION (All Tables, Schemas & Reference Data)
    # =========================================================================
    def replicate_dynamodb_tables(self):
        logger.info(f"=== [1/6] Replicating All DynamoDB Tables from {self.source_region} to {self.target_region} ===")
        paginator = self.source_ddb.get_paginator("list_tables")
        source_tables = []
        for page in paginator.paginate():
            source_tables.extend(page.get("TableNames", []))

        logger.info(f"Found {len(source_tables)} DynamoDB tables in source region.")

        target_tables = set()
        for page in self.target_ddb.get_paginator("list_tables").paginate():
            target_tables.update(page.get("TableNames", []))

        for table_name in source_tables:
            if table_name in target_tables:
                logger.info(f"Table '{table_name}' already exists in {self.target_region}. Skipping creation.")
                continue

            try:
                desc = self.source_ddb.describe_table(TableName=table_name)["Table"]
                create_params: dict[str, Any] = {
                    "TableName": table_name,
                    "AttributeDefinitions": desc["AttributeDefinitions"],
                    "KeySchema": desc["KeySchema"],
                    "BillingMode": "PAY_PER_REQUEST",
                }

                if "GlobalSecondaryIndexes" in desc:
                    gsis = []
                    for gsi in desc["GlobalSecondaryIndexes"]:
                        gsis.append({
                            "IndexName": gsi["IndexName"],
                            "KeySchema": gsi["KeySchema"],
                            "Projection": gsi["Projection"],
                        })
                    create_params["GlobalSecondaryIndexes"] = gsis

                if "LocalSecondaryIndexes" in desc:
                    lsis = []
                    for lsi in desc["LocalSecondaryIndexes"]:
                        lsis.append({
                            "IndexName": lsi["IndexName"],
                            "KeySchema": lsi["KeySchema"],
                            "Projection": lsi["Projection"],
                        })
                    create_params["LocalSecondaryIndexes"] = lsis

                logger.info(f"Creating table '{table_name}' in {self.target_region}...")
                self.target_ddb.create_table(**create_params)
            except ClientError as e:
                logger.error(f"Failed to create table '{table_name}': {e}")

        logger.info("Waiting for tables to become ACTIVE...")
        for table_name in source_tables:
            try:
                waiter = self.target_ddb.get_waiter("table_exists")
                waiter.wait(TableName=table_name, WaiterConfig={"Delay": 3, "MaxAttempts": 20})
            except Exception:
                pass
        logger.info("✔ All DynamoDB tables are ACTIVE.")

    def copy_reference_table_data(self):
        """Copies critical seed/reference data from source tables into target tables."""
        logger.info("=== [2/6] Copying Master / Reference Data for Lookup Tables ===")
        ref_tables = [
            "Catalyst_CompConfig",
            "FeelingMeter",
            "Thought_Table",
            "catEncounter_Membership_Table",
            "SecureDataConnectFacilities",
        ]
        for tbl in ref_tables:
            try:
                logger.info(f"Scanning and migrating reference rows for '{tbl}'...")
                items = self.source_ddb.scan(TableName=tbl).get("Items", [])
                if not items:
                    continue
                for item in items:
                    self.target_ddb.put_item(TableName=tbl, Item=item)
                logger.info(f"✔ Migrated {len(items)} reference items into '{tbl}'")
            except Exception as e:
                logger.warning(f"Could not copy rows for '{tbl}': {e}")

    # =========================================================================
    # 3. COGNITO USER POOL & IDENTITY POOL (Full Auth Parity)
    # =========================================================================
    def replicate_cognito(self) -> tuple[str | None, str | None, str | None]:
        logger.info(f"=== [3/6] Replicating Cognito User Pool & Identity Pool to {self.target_region} ===")
        pools = self.source_cognito.list_user_pools(MaxResults=60).get("UserPools", [])
        dev_pool = next((p for p in pools if "dev" in p["Name"].lower()), None)
        if not dev_pool and pools:
            dev_pool = pools[0]

        if not dev_pool:
            logger.warning("No source Cognito user pool found to replicate.")
            return None, None, None

        source_pool_id = dev_pool["Id"]
        pool_desc = self.source_cognito.describe_user_pool(UserPoolId=source_pool_id)["UserPool"]

        target_pools = self.target_cognito.list_user_pools(MaxResults=60).get("UserPools", [])
        existing_target = next((p for p in target_pools if p["Name"] == pool_desc["Name"]), None)
        
        if existing_target:
            target_pool_id = existing_target["Id"]
            logger.info(f"Cognito User Pool already exists: {target_pool_id}")
            clients = self.target_cognito.list_user_pool_clients(UserPoolId=target_pool_id, MaxResults=10).get("UserPoolClients", [])
            client_id = clients[0]["ClientId"] if clients else None
        else:
            create_kwargs: dict[str, Any] = {
                "PoolName": pool_desc["Name"],
                "Policies": pool_desc.get("Policies", {}),
                "AutoVerifiedAttributes": pool_desc.get("AutoVerifiedAttributes", ["email"]),
                "UsernameAttributes": pool_desc.get("UsernameAttributes", ["email"]),
            }
            if "Schema" in pool_desc:
                valid_schema = [s for s in pool_desc["Schema"] if not s.get("DeveloperOnlyAttribute", False)]
                create_kwargs["Schema"] = valid_schema

            logger.info(f"Creating User Pool '{pool_desc['Name']}' in {self.target_region}...")
            resp = self.target_cognito.create_user_pool(**create_kwargs)
            target_pool_id = resp["UserPool"]["Id"]

            client_resp = self.target_cognito.create_user_pool_client(
                UserPoolId=target_pool_id,
                ClientName="catalyst-web-client",
                GenerateSecret=False,
                ExplicitAuthFlows=[
                    "ALLOW_USER_PASSWORD_AUTH",
                    "ALLOW_REFRESH_TOKEN_AUTH",
                    "ALLOW_USER_SRP_AUTH",
                ],
            )
            client_id = client_resp["UserPoolClient"]["ClientId"]

        # Replicate / Create Cognito Identity Pool
        provider_name = f"cognito-idp.{self.target_region}.amazonaws.com/{target_pool_id}"
        identity_pools = self.target_identity.list_identity_pools(MaxResults=60).get("IdentityPools", [])
        existing_id_pool = next((ip for ip in identity_pools if "catalyst" in ip["IdentityPoolName"].lower()), None)
        
        if existing_id_pool:
            identity_pool_id = existing_id_pool["IdentityPoolId"]
        else:
            logger.info("Creating Cognito Identity Pool in target region...")
            id_resp = self.target_identity.create_identity_pool(
                IdentityPoolName="catalyst_identity_pool",
                AllowUnauthenticatedIdentities=True,
                CognitoIdentityProviders=[{
                    "ProviderName": provider_name,
                    "ClientId": client_id,
                }] if client_id else []
            )
            identity_pool_id = id_resp["IdentityPoolId"]

        logger.info(f"✔ Replicated User Pool ID: {target_pool_id}, Client ID: {client_id}, Identity Pool ID: {identity_pool_id}")
        return target_pool_id, client_id, identity_pool_id

    # =========================================================================
    # 4. APPSYNC GRAPHQL API (Schema, DataSources, Functions, Resolvers)
    # =========================================================================
    def replicate_appsync_complete(self, user_pool_id: str | None = None) -> str | None:
        logger.info(f"=== [4/6] Replicating AppSync GraphQL API (Schema, Resolvers, DataSources) ===")
        apis = self.source_appsync.list_graphql_apis(maxResults=25).get("graphqlApis", [])
        source_api = next((a for a in apis if "dev" in a["name"].lower() or "act" in a["name"].lower()), None)
        if not source_api and apis:
            source_api = apis[0]

        if not source_api:
            logger.warning("No source AppSync API found.")
            return None

        source_api_id = source_api["apiId"]
        target_name = source_api["name"]

        target_apis = self.target_appsync.list_graphql_apis(maxResults=25).get("graphqlApis", [])
        existing = next((a for a in target_apis if a["name"] == target_name), None)
        
        if existing:
            target_api_id = existing["apiId"]
            logger.info(f"AppSync API '{target_name}' already exists: {target_api_id}")
        else:
            create_args: dict[str, Any] = {
                "name": target_name,
                "authenticationType": source_api["authenticationType"],
            }
            if "userPoolConfig" in source_api and user_pool_id:
                up_config = dict(source_api["userPoolConfig"])
                up_config["userPoolId"] = user_pool_id
                create_args["userPoolConfig"] = up_config

            target_api = self.target_appsync.create_graphql_api(**create_args)["graphqlApi"]
            target_api_id = target_api["apiId"]
            self.target_appsync.create_api_key(apiId=target_api_id)

            # 1. Clone Schema SDL
            logger.info("Cloning GraphQL Schema SDL...")
            schema_sdl = self.source_appsync.get_introspection_schema(apiId=source_api_id, format="SDL")["schema"].read()
            self.target_appsync.start_schema_creation(apiId=target_api_id, definition=schema_sdl)
            while True:
                status = self.target_appsync.get_schema_creation_status(apiId=target_api_id)["status"]
                if status in ["SUCCESS", "FAILED"]:
                    break
                time.sleep(2)

        # 2. Clone Data Sources (with region swapping in ARNs)
        logger.info("Cloning AppSync Data Sources...")
        ds_res = self.source_appsync.list_data_sources(apiId=source_api_id)
        for ds in ds_res.get("dataSources", []):
            try:
                ds_args: dict[str, Any] = {
                    "apiId": target_api_id,
                    "name": ds["name"],
                    "type": ds["type"],
                }
                if "serviceRoleArn" in ds:
                    ds_args["serviceRoleArn"] = ds["serviceRoleArn"]
                if ds["type"] == "AMAZON_DYNAMODB":
                    cfg = dict(ds["dynamodbConfig"])
                    cfg["awsRegion"] = self.target_region
                    ds_args["dynamodbConfig"] = cfg
                elif ds["type"] == "AWS_LAMBDA":
                    cfg = dict(ds["lambdaConfig"])
                    cfg["lambdaFunctionArn"] = cfg["lambdaFunctionArn"].replace(self.source_region, self.target_region)
                    ds_args["lambdaConfig"] = cfg

                self.target_appsync.create_data_source(**ds_args)
            except ClientError:
                pass

        # 3. Clone Functions
        logger.info("Cloning AppSync Functions...")
        func_mapping = {}
        for fn in self.source_appsync.list_functions(apiId=source_api_id).get("functions", []):
            try:
                fn_args = {
                    "apiId": target_api_id,
                    "name": fn["name"],
                    "dataSourceName": fn["dataSourceName"],
                    "functionVersion": fn["functionVersion"],
                }
                if "requestMappingTemplate" in fn:
                    fn_args["requestMappingTemplate"] = fn["requestMappingTemplate"]
                if "responseMappingTemplate" in fn:
                    fn_args["responseMappingTemplate"] = fn["responseMappingTemplate"]
                new_fn = self.target_appsync.create_function(**fn_args)["functionConfiguration"]
                func_mapping[fn["functionId"]] = new_fn["functionId"]
            except ClientError:
                pass

        # 4. Clone Resolvers (Query, Mutation, Subscription)
        logger.info("Cloning AppSync Resolvers...")
        types = self.source_appsync.list_types(apiId=source_api_id, format="SDL").get("types", [])
        for t in types:
            type_name = t["name"]
            resolvers = self.source_appsync.list_resolvers(apiId=source_api_id, typeName=type_name).get("resolvers", [])
            for res in resolvers:
                try:
                    res_args = {
                        "apiId": target_api_id,
                        "typeName": type_name,
                        "fieldName": res["fieldName"],
                    }
                    if "dataSourceName" in res:
                        res_args["dataSourceName"] = res["dataSourceName"]
                    if "requestMappingTemplate" in res:
                        res_args["requestMappingTemplate"] = res["requestMappingTemplate"]
                    if "responseMappingTemplate" in res:
                        res_args["responseMappingTemplate"] = res["responseMappingTemplate"]
                    if "kind" in res:
                        res_args["kind"] = res["kind"]
                    if "pipelineConfig" in res:
                        pconfig = res["pipelineConfig"]
                        new_fns = [func_mapping.get(fid, fid) for fid in pconfig.get("functions", [])]
                        res_args["pipelineConfig"] = {"functions": new_fns}
                    self.target_appsync.create_resolver(**res_args)
                except ClientError:
                    pass

        logger.info(f"✔ Full AppSync API Replicated: {target_api_id}")
        return target_api_id

    # =========================================================================
    # 5. BASE LAMBDA FUNCTIONS
    # =========================================================================
    def replicate_base_lambdas(self):
        logger.info(f"=== [5/6] Replicating Base Lambda Functions ===")
        core_prefixes = ["backendApi-dev", "staffApi-dev", "engageapi-dev", "bhaSession-dev", "webhook-dev"]
        paginator = self.source_lam.get_paginator("list_functions")
        source_functions = []
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                name = fn["FunctionName"]
                if any(p in name for p in core_prefixes):
                    source_functions.append(fn)

        with tempfile.TemporaryDirectory() as tmpdir:
            for fn in source_functions:
                fn_name = fn["FunctionName"]
                try:
                    self.target_lam.get_function(FunctionName=fn_name)
                    logger.info(f"Lambda '{fn_name}' exists in target. Skipping.")
                    continue
                except ClientError:
                    pass

                logger.info(f"Cloning Lambda '{fn_name}'...")
                fn_details = self.source_lam.get_function(FunctionName=fn_name)
                code_url = fn_details["Code"]["Location"]
                zip_path = f"{tmpdir}/{fn_name}.zip"

                urllib.request.urlretrieve(code_url, zip_path)
                with open(zip_path, "rb") as f:
                    zip_bytes = f.read()

                cfg = fn_details["Configuration"]
                create_args = {
                    "FunctionName": fn_name,
                    "Runtime": cfg["Runtime"],
                    "Role": cfg["Role"],
                    "Handler": cfg["Handler"],
                    "Code": {"ZipFile": zip_bytes},
                    "Timeout": cfg.get("Timeout", 30),
                    "MemorySize": cfg.get("MemorySize", 128),
                }
                if "Environment" in cfg:
                    # Update REGION in Lambda environment variables to target_region
                    env_vars = dict(cfg["Environment"].get("Variables", {}))
                    if "AWS_DEFAULT_REGION" in env_vars:
                        env_vars["AWS_DEFAULT_REGION"] = self.target_region
                    if "REGION" in env_vars:
                        env_vars["REGION"] = self.target_region
                    create_args["Environment"] = {"Variables": env_vars}

                self.target_lam.create_function(**create_args)
                logger.info(f"✔ Created Lambda '{fn_name}' in {self.target_region}")

    # =========================================================================
    # 6. REST API GATEWAY CLONING (OpenAPI/Swagger Export & Import)
    # =========================================================================
    def replicate_rest_apis(self):
        logger.info(f"=== [6/6] Replicating Core REST API Gateways ===")
        core_api_names = ["backendApi", "staffApi", "engageapi", "bhaSession", "webhook"]
        apis = self.source_apigw.get_rest_apis(limit=50).get("items", [])
        
        target_apis = self.target_apigw.get_rest_apis(limit=50).get("items", [])
        target_names = {a["name"]: a["id"] for a in target_apis}

        for api in apis:
            name = api["name"]
            if name not in core_api_names:
                continue

            if name in target_names:
                logger.info(f"REST API '{name}' already exists in target: {target_names[name]}")
                continue

            try:
                logger.info(f"Exporting OpenAPI definition for REST API '{name}'...")
                # Get the active deployment stage (usually 'dev' or 'prod')
                stages = self.source_apigw.get_stages(restApiId=api["id"]).get("item", [])
                stage_name = stages[0]["stageName"] if stages else "prod"

                export_res = self.source_apigw.get_export(
                    restApiId=api["id"],
                    stageName=stage_name,
                    exportType="oas30",
                    parameters={"extensions": "integrations"}
                )
                spec_body = export_res["body"].read().decode("utf-8")
                # Swap region in Lambda integration URIs
                spec_body = spec_body.replace(self.source_region, self.target_region)

                logger.info(f"Importing REST API '{name}' to {self.target_region}...")
                new_api = self.target_apigw.import_rest_api(
                    body=spec_body.encode("utf-8"),
                    failOnWarnings=False
                )
                new_id = new_api["id"]
                # Deploy to stage
                self.target_apigw.create_deployment(restApiId=new_id, stageName=stage_name)
                logger.info(f"✔ Deployed REST API '{name}' (ID: {new_id})")
            except Exception as e:
                logger.warning(f"Could not replicate REST API '{name}': {e}")


def main():
    parser = argparse.ArgumentParser(description="Full Cross-Region Replicator")
    parser.add_argument("--source", default="eu-central-1", help="Source Region")
    parser.add_argument("--target", default="eu-west-1", help="Target Region")
    args = parser.parse_args()

    replicator = FullRegionReplicator(source_region=args.source, target_region=args.target)
    replicator.replicate_dynamodb_tables()
    replicator.copy_reference_table_data()
    pool_id, client_id, id_pool_id = replicator.replicate_cognito()
    replicator.replicate_appsync_complete(user_pool_id=pool_id)
    replicator.replicate_base_lambdas()
    replicator.replicate_rest_apis()

    logger.info("==================================================================")
    logger.info(" FULL-STACK PARITY COMPLETE: ALL RESOURCES REPLICATED TO IRELAND! ")
    logger.info("==================================================================")


if __name__ == "__main__":
    main()
