#!/usr/bin/env python3
"""
create_dev_appsync_api.py — Recreate the dev AppSync GraphQL API by cloning
an existing template API (schema, data sources, functions, resolvers, API key, and tags).
"""
import argparse
import logging
import sys
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("CreateDevAppSync")


def get_all_apis(client: Any) -> list[dict]:
    """List all GraphQL APIs handling pagination."""
    apis = []
    next_token = None
    while True:
        kwargs = {"maxResults": 25}
        if next_token:
            kwargs["nextToken"] = next_token
        res = client.list_graphql_apis(**kwargs)
        apis.extend(res.get("graphqlApis", []))
        next_token = res.get("nextToken")
        if not next_token:
            break
    return apis


def find_source_api(client: Any, identifier: str | None) -> dict | None:
    """Find source API by ID or by name."""
    apis = get_all_apis(client)
    if not apis:
        return None

    if identifier:
        # Check by ID
        for a in apis:
            if a["apiId"] == identifier:
                return a
        # Check by exact name
        for a in apis:
            if a["name"] == identifier:
                return a
        # Check by substring
        for a in apis:
            if identifier.lower() in a["name"].lower():
                return a

    # Default preference order if not specified
    preferred_names = ["catalyst-api-act", "catalyst-api-acttest", "catalyst-api-live-demo-corp"]
    for pref in preferred_names:
        for a in apis:
            if a["name"] == pref:
                return a

    # Fallback to the first available API
    return apis[0]


def clone_schema(client: Any, source_api_id: str, target_api_id: str) -> None:
    logger.info("Fetching introspection schema (SDL) from source API...")
    res = client.get_introspection_schema(apiId=source_api_id, format="SDL")
    schema_sdl = res["schema"].read()

    logger.info("Uploading schema to target API...")
    client.start_schema_creation(apiId=target_api_id, definition=schema_sdl)

    logger.info("Waiting for schema creation to complete...")
    for _ in range(60):
        status_res = client.get_schema_creation_status(apiId=target_api_id)
        status = status_res.get("status")
        if status == "SUCCESS":
            logger.info("Schema creation SUCCESS.")
            return
        elif status == "FAILED":
            details = status_res.get("details", "No details")
            raise RuntimeError(f"Schema creation failed: {details}")
        time.sleep(2)
    raise TimeoutError("Schema creation timed out after 120s.")


def clone_data_sources(client: Any, source_api_id: str, target_api_id: str) -> dict[str, str]:
    logger.info("Cloning data sources...")
    ds_mapping = {}
    next_token = None

    while True:
        kwargs = {"apiId": source_api_id}
        if next_token:
            kwargs["nextToken"] = next_token
        res = client.list_data_sources(**kwargs)

        for ds in res.get("dataSources", []):
            ds_name = ds["name"]
            ds_type = ds["type"]
            create_args: dict[str, Any] = {
                "apiId": target_api_id,
                "name": ds_name,
                "type": ds_type,
            }
            if "description" in ds:
                create_args["description"] = ds["description"]
            if "serviceRoleArn" in ds:
                create_args["serviceRoleArn"] = ds["serviceRoleArn"]

            if ds_type == "AMAZON_DYNAMODB":
                create_args["dynamodbConfig"] = dict(ds["dynamodbConfig"])
            elif ds_type == "AWS_LAMBDA":
                create_args["lambdaConfig"] = dict(ds["lambdaConfig"])
            elif ds_type == "HTTP":
                create_args["httpConfig"] = dict(ds["httpConfig"])
            elif ds_type == "RELATIONAL_DATABASE":
                create_args["relationalDatabaseConfig"] = dict(ds["relationalDatabaseConfig"])
            elif ds_type == "AMAZON_EVENTBRIDGE":
                create_args["eventBridgeConfig"] = dict(ds["eventBridgeConfig"])
            elif ds_type == "AMAZON_OPENSEARCH_SERVICE":
                create_args["openSearchServiceConfig"] = dict(ds["openSearchServiceConfig"])

            try:
                client.create_data_source(**create_args)
                logger.info("Created data source: %s (%s)", ds_name, ds_type)
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "AlreadyExistsException":
                    logger.warning("Data source %s already exists, skipping.", ds_name)
                else:
                    logger.error("Failed to create data source %s: %s", ds_name, exc)
                    raise
            ds_mapping[ds_name] = ds_name

        next_token = res.get("nextToken")
        if not next_token:
            break

    return ds_mapping


def clone_functions(client: Any, source_api_id: str, target_api_id: str) -> dict[str, str]:
    logger.info("Cloning AppSync functions...")
    func_mapping = {}
    next_token = None

    while True:
        kwargs = {"apiId": source_api_id}
        if next_token:
            kwargs["nextToken"] = next_token
        res = client.list_functions(**kwargs)

        for fn in res.get("functions", []):
            create_args: dict[str, Any] = {
                "apiId": target_api_id,
                "name": fn["name"],
                "dataSourceName": fn["dataSourceName"],
                "functionVersion": fn["functionVersion"],
            }
            for attr in [
                "description",
                "requestMappingTemplate",
                "responseMappingTemplate",
                "code",
                "runtime",
                "maxBatchSize",
            ]:
                if attr in fn:
                    create_args[attr] = fn[attr]

            try:
                created = client.create_function(**create_args)["functionConfiguration"]
                func_mapping[fn["functionId"]] = created["functionId"]
                logger.info("Created function: %s -> %s", fn["name"], created["functionId"])
            except ClientError as exc:
                logger.warning("Failed to clone function %s: %s", fn["name"], exc)

        next_token = res.get("nextToken")
        if not next_token:
            break

    return func_mapping


def clone_resolvers(
    client: Any, source_api_id: str, target_api_id: str, func_mapping: dict[str, str]
) -> None:
    logger.info("Cloning resolvers...")
    types: list[dict] = []
    next_token = None

    while True:
        kwargs = {"apiId": source_api_id, "format": "SDL"}
        if next_token:
            kwargs["nextToken"] = next_token
        types_res = client.list_types(**kwargs)
        types.extend(types_res.get("types", []))
        next_token = types_res.get("nextToken")
        if not next_token:
            break

    for t in types:
        type_name = t["name"]
        res_next_token = None

        while True:
            r_kwargs = {"apiId": source_api_id, "typeName": type_name}
            if res_next_token:
                r_kwargs["nextToken"] = res_next_token
            res_list = client.list_resolvers(**r_kwargs)

            for res in res_list.get("resolvers", []):
                field_name = res["fieldName"]
                create_args: dict[str, Any] = {
                    "apiId": target_api_id,
                    "typeName": type_name,
                    "fieldName": field_name,
                }
                for attr in [
                    "dataSourceName",
                    "requestMappingTemplate",
                    "responseMappingTemplate",
                    "kind",
                    "code",
                    "runtime",
                    "maxBatchSize",
                    "cachingConfig",
                    "syncConfig",
                ]:
                    if attr in res:
                        create_args[attr] = res[attr]

                if "pipelineConfig" in res:
                    pconfig = res["pipelineConfig"]
                    new_funcs = [
                        func_mapping.get(fid, fid) for fid in pconfig.get("functions", [])
                    ]
                    create_args["pipelineConfig"] = {"functions": new_funcs}

                try:
                    client.create_resolver(**create_args)
                    logger.info("Created resolver: %s.%s", type_name, field_name)
                except ClientError as exc:
                    logger.warning("Failed to create resolver %s.%s: %s", type_name, field_name, exc)

            res_next_token = res_list.get("nextToken")
            if not res_next_token:
                break


def main():
    parser = argparse.ArgumentParser(description="Create or recreate the dev AppSync GraphQL API.")
    parser.add_argument("--region", default="eu-central-1", help="AWS Region (default: eu-central-1)")
    parser.add_argument("--source-api-id", default=None, help="Source API ID to clone from (e.g. hcgoaswkxrfivf5wv4uoegrrui)")
    parser.add_argument("--target-name", default="catalyst-api-dev", help="Target API name (default: catalyst-api-dev)")
    parser.add_argument("--user-pool-id", default="eu-central-1_sqttUUuia", help="Cognito User Pool ID for dev (default: eu-central-1_sqttUUuia)")
    args = parser.parse_args()

    client = boto3.client("appsync", region_name=args.region)

    logger.info("Looking for source AppSync API in %s...", args.region)
    source_api = find_source_api(client, args.source_api_id)
    if not source_api:
        logger.error("No source AppSync API could be found to clone from.")
        sys.exit(1)

    source_api_id = source_api["apiId"]
    logger.info("Selected source API: %s (ID: %s)", source_api["name"], source_api_id)

    # Check if target API already exists
    existing_apis = get_all_apis(client)
    for api in existing_apis:
        if api["name"] == args.target_name:
            logger.warning("An API named '%s' already exists with ID: %s", args.target_name, api["apiId"])
            # Ensure tag is present
            client.tag_resource(
                resourceArn=api["arn"],
                tags={"amplify:environment-name": "dev", "Environment": "dev"},
            )
            logger.info("Tagged existing API %s with amplify:environment-name=dev.", api["apiId"])
            print(f"\nTarget API already exists and is now tagged:\nAPI ID: {api['apiId']}\nName: {api['name']}")
            return

    # Fetch source API details
    source_details = client.get_graphql_api(apiId=source_api_id)["graphqlApi"]

    create_args: dict[str, Any] = {
        "name": args.target_name,
        "authenticationType": source_details["authenticationType"],
        "tags": {
            "amplify:environment-name": "dev",
            "Environment": "dev",
            "Project": "Catalyst",
        },
    }

    if "userPoolConfig" in source_details:
        up_config = dict(source_details["userPoolConfig"])
        if args.user_pool_id:
            up_config["userPoolId"] = args.user_pool_id
        create_args["userPoolConfig"] = up_config

    if "additionalAuthenticationProviders" in source_details:
        providers = []
        for prov in source_details["additionalAuthenticationProviders"]:
            p = dict(prov)
            if "userPoolConfig" in p and args.user_pool_id:
                p["userPoolConfig"]["userPoolId"] = args.user_pool_id
            providers.append(p)
        create_args["additionalAuthenticationProviders"] = providers

    if "openIDConnectConfig" in source_details:
        create_args["openIDConnectConfig"] = source_details["openIDConnectConfig"]
    if "lambdaAuthorizerConfig" in source_details:
        create_args["lambdaAuthorizerConfig"] = source_details["lambdaAuthorizerConfig"]
    if "xrayEnabled" in source_details:
        create_args["xrayEnabled"] = source_details["xrayEnabled"]

    logger.info("Creating AppSync GraphQL API '%s'...", args.target_name)
    target_api = client.create_graphql_api(**create_args)["graphqlApi"]
    target_api_id = target_api["apiId"]
    graphql_url = target_api.get("uris", {}).get("GRAPHQL", "")
    logger.info("Created GraphQL API. ID: %s | URL: %s", target_api_id, graphql_url)

    # Create API Key
    api_key_id = ""
    try:
        key_resp = client.create_api_key(apiId=target_api_id, description="Dev API Key")
        api_key_id = key_resp.get("apiKey", {}).get("id", "")
        logger.info("Created API Key: %s", api_key_id)
    except Exception as e:
        logger.warning("Could not create API Key: %s", e)

    try:
        # Clone Schema
        clone_schema(client, source_api_id, target_api_id)

        # Clone Data Sources
        clone_data_sources(client, source_api_id, target_api_id)

        # Clone Functions
        func_mapping = clone_functions(client, source_api_id, target_api_id)

        # Clone Resolvers
        clone_resolvers(client, source_api_id, target_api_id, func_mapping)

        logger.info("Successfully recreated dev AppSync API!")
        print("\n" + "=" * 60)
        print(" Dev AppSync API Created Successfully!")
        print("=" * 60)
        print(f"API Name:        {args.target_name}")
        print(f"API ID:          {target_api_id}")
        print(f"GraphQL Endpoint: {graphql_url}")
        print(f"API Key:         {api_key_id}")
        print(f"Tag:             amplify:environment-name=dev")
        print("=" * 60 + "\n")

    except Exception as err:
        logger.error("Error occurred while cloning components: %s", err)
        print(f"\n[WARNING] AppSync API {target_api_id} was created, but failed to clone all components: {err}")
        print(f"API ID is: {target_api_id}")
        sys.exit(1)


if __name__ == "__main__":
    main()
