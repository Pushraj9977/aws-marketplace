import time
from typing import Any

from pydantic import ConfigDict

from .base import BaseProvisioner
from ..common.constants import ResourceType
from ..common.models import EnvironmentModel, ResourceRecord
from ..common.utils import retry

class AppSyncProvisioner(BaseProvisioner):
    """
    Clones an AWS AppSync GraphQL API including:
    - Schema
    - Data Sources (DynamoDB, Lambda, etc.)
    - Functions
    - Resolvers
    """
    resource_type = ResourceType.APPSYNC_API
    def _create(self, env: EnvironmentModel) -> ResourceRecord:
        client = self.get_client("appsync")
        
        # 1. Find source API
        source_api_id = self._find_source_api(client, env.source_env_name)
        if not source_api_id:
            raise ValueError(f"Could not find source AppSync API for environment: {env.source_env_name}")
            
        self.logger.info("Found source AppSync API", extra={"source_api_id": source_api_id})
        
        # 2. Check if target API already exists
        target_name = f"catalyst-api-{env.target_env_name}"
        existing_target_id = self._find_api_by_name(client, target_name)
        if existing_target_id:
            self.logger.warning("Target AppSync API already exists", extra={"api_id": existing_target_id})
            env.appsync_api_id = existing_target_id
            return ResourceRecord(
                resource_type=self.resource_type,
                source_id=source_api_id,
                target_id=existing_target_id,
                status="DONE"
            )

        # 3. Create target API
        self.logger.info("Creating Target AppSync API", extra={"name": target_name})
        source_api_details = client.get_graphql_api(apiId=source_api_id)["graphqlApi"]
        
        create_args = {
            "name": target_name,
            "authenticationType": source_api_details["authenticationType"]
        }
        if "userPoolConfig" in source_api_details:
            up_config = source_api_details["userPoolConfig"]
            # Swap user pool ID to the new one
            up_config["userPoolId"] = env.user_pool_id
            create_args["userPoolConfig"] = up_config
            
        if "additionalAuthenticationProviders" in source_api_details:
            create_args["additionalAuthenticationProviders"] = source_api_details["additionalAuthenticationProviders"]

        target_api = client.create_graphql_api(**create_args)["graphqlApi"]
        target_api_id = target_api["apiId"]
        env.appsync_api_id = target_api_id
        env.appsync_graphql_url = target_api.get("uris", {}).get("GRAPHQL", "")
        
        # Create an API Key for the new AppSync API
        try:
            key_resp = client.create_api_key(apiId=target_api_id)
            env.appsync_api_key = key_resp.get("apiKey", {}).get("id", "")
            self.logger.info("Created AppSync API Key")
        except Exception as e:
            self.logger.warning(f"Failed to create AppSync API Key: {e}")
            env.appsync_api_key = ""
        
        self.logger.info("Created AppSync API", extra={"api_id": target_api_id})

        # 4. Clone Schema
        self._clone_schema(client, source_api_id, target_api_id)
        
        # 5. Clone Data Sources
        ds_mapping = self._clone_data_sources(client, source_api_id, target_api_id, env)
        
        # 6. Clone Functions
        func_mapping = self._clone_functions(client, source_api_id, target_api_id, ds_mapping)
        
        # 7. Clone Resolvers
        self._clone_resolvers(client, source_api_id, target_api_id, ds_mapping, func_mapping)

        return ResourceRecord(
            resource_type=self.resource_type,
            source_id=source_api_id,
            target_id=target_api_id,
            target_arn=target_api["arn"],
            metadata={"graphql_url": env.appsync_graphql_url}
        )

    def _find_source_api(self, client: Any, source_env_name: str) -> str | None:
        """Find the AppSync API associated with the source environment."""
        apis = client.list_graphql_apis(maxResults=25).get("graphqlApis", [])
        for api in apis:
            # Check tags first
            tags = api.get("tags", {})
            if tags.get("amplify:environment-name") == source_env_name:
                return api["apiId"]
            # Fallback to name check
            if source_env_name in api["name"]:
                return api["apiId"]
        return None

    def _find_api_by_name(self, client: Any, name: str) -> str | None:
        apis = client.list_graphql_apis(maxResults=25).get("graphqlApis", [])
        for api in apis:
            if api["name"] == name:
                return api["apiId"]
        return None

    def _clone_schema(self, client: Any, source_api_id: str, target_api_id: str):
        self.logger.info("Cloning schema...")
        res = client.get_introspection_schema(apiId=source_api_id, format="SDL")
        schema_sdl = res["schema"].read()
        
        client.start_schema_creation(apiId=target_api_id, definition=schema_sdl)
        
        # Wait for schema creation
        while True:
            status = client.get_schema_creation_status(apiId=target_api_id)["status"]
            if status == "SUCCESS":
                break
            elif status == "FAILED":
                raise Exception("Schema creation failed")
            time.sleep(2)

    def _clone_data_sources(self, client: Any, source_api_id: str, target_api_id: str, env: EnvironmentModel) -> dict:
        self.logger.info("Cloning data sources...")
        ds_mapping = {} # maps source ds name to target ds name (they are usually the same, but we modify the config)
        
        res = client.list_data_sources(apiId=source_api_id)
        for ds in res.get("dataSources", []):
            ds_name = ds["name"]
            ds_type = ds["type"]
            
            create_args = {
                "apiId": target_api_id,
                "name": ds_name,
                "type": ds_type
            }
            if "serviceRoleArn" in ds:
                create_args["serviceRoleArn"] = ds["serviceRoleArn"]
            
            if ds_type == "AMAZON_DYNAMODB":
                config = ds["dynamodbConfig"]
                # Swap table name
                old_table = config["tableName"]
                new_table = old_table.replace(env.source_env_name, env.target_env_name)
                config["tableName"] = new_table
                create_args["dynamodbConfig"] = config
                
            elif ds_type == "AWS_LAMBDA":
                config = ds["lambdaConfig"]
                old_arn = config["lambdaFunctionArn"]
                new_arn = old_arn.replace(env.source_env_name, env.target_env_name)
                config["lambdaFunctionArn"] = new_arn
                create_args["lambdaConfig"] = config

            client.create_data_source(**create_args)
            ds_mapping[ds_name] = ds_name
            
        return ds_mapping

    def _clone_functions(self, client: Any, source_api_id: str, target_api_id: str, ds_mapping: dict) -> dict:
        self.logger.info("Cloning functions...")
        func_mapping = {}
        
        res = client.list_functions(apiId=source_api_id)
        for fn in res.get("functions", []):
            create_args = {
                "apiId": target_api_id,
                "name": fn["name"],
                "dataSourceName": fn["dataSourceName"], # Should exist from previous step
                "functionVersion": fn["functionVersion"]
            }
            if "requestMappingTemplate" in fn:
                create_args["requestMappingTemplate"] = fn["requestMappingTemplate"]
            if "responseMappingTemplate" in fn:
                create_args["responseMappingTemplate"] = fn["responseMappingTemplate"]
                
            new_fn = client.create_function(**create_args)["functionConfiguration"]
            func_mapping[fn["functionId"]] = new_fn["functionId"]
            
        return func_mapping

    def _clone_resolvers(self, client: Any, source_api_id: str, target_api_id: str, ds_mapping: dict, func_mapping: dict):
        self.logger.info("Cloning resolvers...")
        
        # We need to list all types to list their resolvers. 
        # AppSync 'list_types' requires API ID.
        types_res = client.list_types(apiId=source_api_id, format="SDL")
        
        for t in types_res.get("types", []):
            type_name = t["name"]
            
            res_list = client.list_resolvers(apiId=source_api_id, typeName=type_name)
            for res in res_list.get("resolvers", []):
                create_args = {
                    "apiId": target_api_id,
                    "typeName": type_name,
                    "fieldName": res["fieldName"],
                }
                if "dataSourceName" in res:
                    create_args["dataSourceName"] = res["dataSourceName"]
                if "requestMappingTemplate" in res:
                    create_args["requestMappingTemplate"] = res["requestMappingTemplate"]
                if "responseMappingTemplate" in res:
                    create_args["responseMappingTemplate"] = res["responseMappingTemplate"]
                if "kind" in res:
                    create_args["kind"] = res["kind"]
                if "pipelineConfig" in res:
                    pconfig = res["pipelineConfig"]
                    # Swap old function IDs for new function IDs
                    new_funcs = [func_mapping.get(fid, fid) for fid in pconfig.get("functions", [])]
                    create_args["pipelineConfig"] = {"functions": new_funcs}
                    
                client.create_resolver(**create_args)

    def validate(self, record: ResourceRecord) -> bool:
        client = self.get_client("appsync")
        try:
            client.get_graphql_api(apiId=record.target_id)
            return True
        except Exception:
            return False
