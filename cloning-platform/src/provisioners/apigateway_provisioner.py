"""
apigateway_provisioner.py — Clone REST API Gateways, one per Lambda function.
Uses wildcard {proxy+} integration pointing to each cloned Lambda.
Automatically configures full CORS (OPTIONS mock integration and 4XX/5XX gateway responses).
"""
from __future__ import annotations

from ..common.constants import ResourceType
from ..common.models import EnvironmentModel, ResourceRecord
from ..common.utils import build_api_url, build_apigw_source_arn, build_lambda_arn, retry
from .base import BaseProvisioner


class APIGatewayProvisioner(BaseProvisioner):
    """Creates one REST API Gateway per cloned Lambda function."""

    resource_type = ResourceType.API_GATEWAY

    def _create(self, env: EnvironmentModel) -> ResourceRecord:
        apigw = self.get_target_client("apigateway")
        lam = self.get_target_client("lambda")

        # Discover cloned Lambda function names
        lam_functions = self._list_target_functions(lam, env.target_env_name)
        if not lam_functions:
            return ResourceRecord(
                resource_type=self.resource_type,
                source_id=env.source_env_name,
                target_id="",
                metadata={"message": "No Lambda functions found — skipping API Gateway"},
            )

        api_urls: dict[str, str] = {}

        for fn_name in lam_functions:
            api_name = f"{fn_name}-api"
            self.logger.info("Wiring API Gateway", extra={"api": api_name, "lambda": fn_name})

            fn_arn = build_lambda_arn(self.target_region, self.account_id, fn_name)
            api_id = self._create_rest_api(apigw, api_name, env)
            root_id = self._get_root_resource_id(apigw, api_id)
            proxy_id = self._add_proxy_resource(apigw, api_id, root_id)
            self._add_lambda_integration(apigw, api_id, proxy_id, fn_arn)
            self._enable_cors(apigw, api_id, root_id, proxy_id)
            self._add_gateway_responses(apigw, api_id)
            self._deploy_stage(apigw, api_id, env.target_env_name)
            self._grant_invoke(lam, fn_name, api_id)

            api_url = build_api_url(api_id, self.target_region, env.target_env_name)
            api_urls[fn_name] = api_url
            self.logger.info("API wired", extra={"api_url": api_url})

        # Inject API URLs into env for downstream consumers
        env.api_urls.update(api_urls)

        # Update Lambda env vars with their individual API_URL
        for fn_name, api_url in api_urls.items():
            try:
                resp = lam.get_function_configuration(FunctionName=fn_name)
                existing_vars = resp.get("Environment", {}).get("Variables", {})
                existing_vars["API_URL"] = api_url
                lam.update_function_configuration(
                    FunctionName=fn_name,
                    Environment={"Variables": existing_vars},
                )
            except Exception as exc:
                self.logger.warning(
                    "Could not inject API_URL into Lambda",
                    extra={"fn": fn_name, "error": str(exc)},
                )

        return ResourceRecord(
            resource_type=self.resource_type,
            source_id=env.source_env_name,
            target_id=",".join(api_urls.values()),
            metadata={"api_urls": api_urls},
        )

    def _list_target_functions(self, lam: object, target_env: str) -> list[str]:
        names: list[str] = []
        paginator = lam.get_paginator("list_functions")  # type: ignore[attr-defined]
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                if target_env in fn["FunctionName"]:
                    names.append(fn["FunctionName"])
        return names

    @retry(max_attempts=3, delay_seconds=2.0)
    def _create_rest_api(self, apigw: object, api_name: str, env: EnvironmentModel) -> str:
        resp = apigw.create_rest_api(  # type: ignore[attr-defined]
            name=api_name,
            description=f"REST API for {env.target_env_name}",
            endpointConfiguration={"types": ["REGIONAL"]},
            tags={"Environment": env.target_env_name, "ManagedBy": "CloningPlatform"},
        )
        return resp["id"]

    def _get_root_resource_id(self, apigw: object, api_id: str) -> str:
        resp = apigw.get_resources(restApiId=api_id)  # type: ignore[attr-defined]
        for item in resp["items"]:
            if item["path"] == "/":
                return item["id"]
        raise ValueError(f"Root resource not found for API {api_id}")

    def _add_proxy_resource(self, apigw: object, api_id: str, root_id: str) -> str:
        resp = apigw.create_resource(  # type: ignore[attr-defined]
            restApiId=api_id, parentId=root_id, pathPart="{proxy+}"
        )
        return resp["id"]

    def _add_lambda_integration(
        self, apigw: object, api_id: str, resource_id: str, fn_arn: str
    ) -> None:
        apigw.put_method(  # type: ignore[attr-defined]
            restApiId=api_id,
            resourceId=resource_id,
            httpMethod="ANY",
            authorizationType="NONE",
        )
        uri = f"arn:aws:apigateway:{self.target_region}:lambda:path/2015-03-31/functions/{fn_arn}/invocations"
        apigw.put_integration(  # type: ignore[attr-defined]
            restApiId=api_id,
            resourceId=resource_id,
            httpMethod="ANY",
            type="AWS_PROXY",
            integrationHttpMethod="POST",
            uri=uri,
        )

    def _enable_cors(self, apigw: object, api_id: str, *resource_ids: str) -> None:
        """Configure mock OPTIONS integration and CORS headers on given resources."""
        headers_str = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,Accept'"
        methods_str = "'GET,OPTIONS,POST,PUT,PATCH,DELETE'"
        origin_str = "'*'"

        for res_id in resource_ids:
            try:
                # Delete old OPTIONS method if exists to avoid ConflictException on rerun
                try:
                    apigw.delete_method(  # type: ignore[attr-defined]
                        restApiId=api_id,
                        resourceId=res_id,
                        httpMethod="OPTIONS",
                    )
                except Exception:
                    pass

                apigw.put_method(  # type: ignore[attr-defined]
                    restApiId=api_id,
                    resourceId=res_id,
                    httpMethod="OPTIONS",
                    authorizationType="NONE",
                )
                apigw.put_integration(  # type: ignore[attr-defined]
                    restApiId=api_id,
                    resourceId=res_id,
                    httpMethod="OPTIONS",
                    type="MOCK",
                    requestTemplates={"application/json": '{"statusCode": 200}'},
                )
                apigw.put_method_response(  # type: ignore[attr-defined]
                    restApiId=api_id,
                    resourceId=res_id,
                    httpMethod="OPTIONS",
                    statusCode="200",
                    responseParameters={
                        "method.response.header.Access-Control-Allow-Headers": True,
                        "method.response.header.Access-Control-Allow-Methods": True,
                        "method.response.header.Access-Control-Allow-Origin": True,
                    },
                )
                apigw.put_integration_response(  # type: ignore[attr-defined]
                    restApiId=api_id,
                    resourceId=res_id,
                    httpMethod="OPTIONS",
                    statusCode="200",
                    responseParameters={
                        "method.response.header.Access-Control-Allow-Headers": headers_str,
                        "method.response.header.Access-Control-Allow-Methods": methods_str,
                        "method.response.header.Access-Control-Allow-Origin": origin_str,
                    },
                )
            except Exception as e:
                self.logger.warning(
                    f"Could not enable CORS on resource {res_id}: {e}",
                    extra={"api_id": api_id, "resource_id": res_id},
                )

    def _add_gateway_responses(self, apigw: object, api_id: str) -> None:
        """Add CORS headers to DEFAULT_4XX and DEFAULT_5XX gateway responses."""
        cors_params = {
            "gatewayresponse.header.Access-Control-Allow-Origin": "'*'",
            "gatewayresponse.header.Access-Control-Allow-Headers": "'*'",
            "gatewayresponse.header.Access-Control-Allow-Methods": "'GET,OPTIONS,POST,PUT,PATCH,DELETE'",
        }
        for resp_type in ["DEFAULT_4XX", "DEFAULT_5XX"]:
            try:
                apigw.put_gateway_response(  # type: ignore[attr-defined]
                    restApiId=api_id,
                    responseType=resp_type,
                    responseParameters=cors_params,
                )
            except Exception as e:
                self.logger.warning(
                    f"Could not add gateway response for {resp_type}: {e}",
                    extra={"api_id": api_id, "response_type": resp_type},
                )

    @retry(max_attempts=5, delay_seconds=5.0)
    def _deploy_stage(self, apigw: object, api_id: str, stage_name: str) -> None:
        apigw.create_deployment(restApiId=api_id, stageName=stage_name)  # type: ignore[attr-defined]

    def _grant_invoke(self, lam: object, fn_name: str, api_id: str) -> None:
        source_arn = build_apigw_source_arn(self.target_region, self.account_id, api_id)
        try:
            lam.add_permission(  # type: ignore[attr-defined]
                FunctionName=fn_name,
                StatementId=f"apigw-{api_id}",
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                SourceArn=source_arn,
            )
        except lam.exceptions.ResourceConflictException:  # type: ignore[attr-defined]
            pass  # Permission already exists — idempotent

    def validate(self, record: ResourceRecord) -> bool:
        if not record.target_id:
            return True
        apigw = self.get_target_client("apigateway")
        try:
            apigw.get_rest_apis()
            return True
        except Exception:
            return False
