import boto3

idp = boto3.client('cognito-idp', region_name='eu-central-1')
# Let's list pools to find the one we just created
pools = idp.list_user_pools(MaxResults=10)
if pools['UserPools']:
    pool_id = pools['UserPools'][0]['Id']
    print(f"Describing pool {pool_id}")
    resp = idp.describe_user_pool(UserPoolId=pool_id)
    print(resp['UserPool'].keys())
    if 'Status' in resp['UserPool']:
        print(f"Status is: {resp['UserPool']['Status']}")
    else:
        print("Status is NOT in the response.")
