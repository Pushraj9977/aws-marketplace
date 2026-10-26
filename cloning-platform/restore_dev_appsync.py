import time
import boto3

REGION = "eu-central-1"
SOURCE_API_ID = "yoh3elzhaza7jijavb5f27aebi" # catalyst-api-testv5-26-10
TARGET_NAME = "catalysthealthyaging-dev"
USER_POOL_ID = "eu-central-1_sqttUUuia"

client = boto3.client("appsync", region_name=REGION)

print(f"1. Checking if {TARGET_NAME} already exists...")
apis = []
token = None
while True:
    kw = {"maxResults": 25}
    if token:
        kw["nextToken"] = token
    r = client.list_graphql_apis(**kw)
    apis.extend(r.get("graphqlApis", []))
    token = r.get("nextToken")
    if not token:
        break

existing = [a for a in apis if a.get("name") == TARGET_NAME]
if existing:
    target_api_id = existing[0]["apiId"]
    print(f"Target API {TARGET_NAME} already exists: {target_api_id}")
else:
    print(f"Creating GraphQL API: {TARGET_NAME}...")
    source_details = client.get_graphql_api(apiId=SOURCE_API_ID)["graphqlApi"]
    
    create_args = {
        "name": TARGET_NAME,
        "authenticationType": "API_KEY",
        "tags": {
            "amplify:environment-name": "dev",
            "user:Application": "CatalystHealthyAging"
        },
        "additionalAuthenticationProviders": [
            {
                "authenticationType": "AMAZON_COGNITO_USER_POOLS",
                "userPoolConfig": {
                    "userPoolId": USER_POOL_ID,
                    "awsRegion": REGION
                }
            }
        ]
    }
    
    created = client.create_graphql_api(**create_args)["graphqlApi"]
    target_api_id = created["apiId"]
    print(f"Created API {TARGET_NAME} with ID: {target_api_id}")
    
    # Create API key
    key = client.create_api_key(apiId=target_api_id, description="Default API Key")
    print(f"Created API key: {key['apiKey']['id']}")

# 2. Schema
print("2. Cloning schema...")
res = client.get_introspection_schema(apiId=SOURCE_API_ID, format="SDL")
schema_sdl = res["schema"].read()
client.start_schema_creation(apiId=target_api_id, definition=schema_sdl)

while True:
    status = client.get_schema_creation_status(apiId=target_api_id)["status"]
    print(f"  Schema status: {status}")
    if status == "SUCCESS":
        break
    elif status == "FAILED":
        raise Exception("Schema creation failed")
    time.sleep(2)

# 3. Data Sources
print("3. Cloning data sources...")
existing_ds = {d["name"]: d for d in client.list_data_sources(apiId=target_api_id).get("dataSources", [])}
source_ds = client.list_data_sources(apiId=SOURCE_API_ID).get("dataSources", [])

for ds in source_ds:
    ds_name = ds["name"]
    if ds_name in existing_ds:
        print(f"  DataSource {ds_name} already exists")
        continue
    ds_type = ds["type"]
    create_args = {
        "apiId": target_api_id,
        "name": ds_name,
        "type": ds_type
    }
    if "serviceRoleArn" in ds:
        create_args["serviceRoleArn"] = ds["serviceRoleArn"]
    if ds_type == "AMAZON_DYNAMODB":
        create_args["dynamodbConfig"] = ds["dynamodbConfig"]
    elif ds_type == "AWS_LAMBDA":
        create_args["lambdaConfig"] = ds["lambdaConfig"]
    elif ds_type == "RELATIONAL_DATABASE":
        create_args["relationalDatabaseConfig"] = ds["relationalDatabaseConfig"]
    elif ds_type == "OPEN_SEARCH":
        create_args["openSearchServiceConfig"] = ds["openSearchServiceConfig"]
    elif ds_type == "EVENTBRIDGE":
        create_args["eventBridgeConfig"] = ds["eventBridgeConfig"]

    client.create_data_source(**create_args)
    print(f"  Created DataSource: {ds_name} ({ds_type})")

# 4. Functions
print("4. Cloning functions...")
existing_fns = {f["name"]: f["functionId"] for f in client.list_functions(apiId=target_api_id).get("functions", [])}
source_fns = client.list_functions(apiId=SOURCE_API_ID).get("functions", [])

func_mapping = {}
for fn in source_fns:
    fn_name = fn["name"]
    old_id = fn["functionId"]
    if fn_name in existing_fns:
        func_mapping[old_id] = existing_fns[fn_name]
        print(f"  Function {fn_name} already exists ({existing_fns[fn_name]})")
        continue
    
    create_args = {
        "apiId": target_api_id,
        "name": fn_name,
        "dataSourceName": fn["dataSourceName"],
        "functionVersion": fn["functionVersion"]
    }
    if "requestMappingTemplate" in fn:
        create_args["requestMappingTemplate"] = fn["requestMappingTemplate"]
    if "responseMappingTemplate" in fn:
        create_args["responseMappingTemplate"] = fn["responseMappingTemplate"]

    new_fn = client.create_function(**create_args)["functionConfiguration"]
    func_mapping[old_id] = new_fn["functionId"]
    print(f"  Created Function: {fn_name} -> {new_fn['functionId']}")

# 5. Resolvers
print("5. Cloning resolvers...")
types_res = client.list_types(apiId=SOURCE_API_ID, format="SDL")

for t in types_res.get("types", []):
    type_name = t["name"]
    res_list = client.list_resolvers(apiId=SOURCE_API_ID, typeName=type_name)
    for res in res_list.get("resolvers", []):
        field_name = res["fieldName"]
        create_args = {
            "apiId": target_api_id,
            "typeName": type_name,
            "fieldName": field_name,
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
            new_funcs = [func_mapping.get(fid, fid) for fid in pconfig.get("functions", [])]
            create_args["pipelineConfig"] = {"functions": new_funcs}
            
        try:
            client.create_resolver(**create_args)
            print(f"  Created Resolver: {type_name}.{field_name}")
        except client.exceptions.ConcurrentModificationException:
            client.update_resolver(**create_args)
            print(f"  Updated Resolver: {type_name}.{field_name}")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"  Resolver {type_name}.{field_name} already exists")
            else:
                print(f"  Error creating resolver {type_name}.{field_name}: {e}")

print(f"\nSUCCESS! Recreated {TARGET_NAME} with ID: {target_api_id}")
