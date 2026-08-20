# Catalyst Multi-Tenant Provisioning Platform

This repository contains the fully automated AWS Step Functions and Lambda pipeline for provisioning new isolated tenant environments for the Catalyst-HealthyAging application suite.

## 🚀 How to Onboard a New Customer (No Code Required)

To provision a brand new, isolated environment for a customer, **no manual coding or script execution is required by the team**.

1. Send the customer to the SaaS Landing Page:
   `http://catalyst-saas-landing-eu-central-1.s3-website.eu-central-1.amazonaws.com`
2. The customer fills out their **Company Name** and **Admin Email**, then clicks Register.
3. The automated pipeline instantly spins up in the background. It will:
   - Create isolated DynamoDB tables
   - Spin up a dedicated Cognito User Pool
   - Generate unique API Keys via AWS Secrets Manager
   - Deploy a dedicated S3 bucket containing the Catalyst Assess frontend
   - Trigger an AWS Amplify build for the Catalyst Staff Portal
   - Automatically inject the customer's unique Cognito IDs and API URLs into their frontends
4. Upon completion, the system sends an email to the customer with their **Admin Credentials** and the **URLs** to both of their deployed applications.

---

## 🛠️ Developer Workflow

If a team member needs to make changes to the code, follow the guidelines below to ensure those changes are picked up by the automation pipeline.

### 1. Updating the Catalyst Assess Frontend (React Code)
If you make changes to the user interface in the `Catalyst-HealthyAging-Assess-test` repository, you must build and upload those changes to the **Base Assets Bucket**. The pipeline uses this base bucket to clone the app for all future tenants.

```bash
cd aws-marketplace-soft-launch
bash scripts/build_and_upload_base.sh
```
*Note: Existing tenants will retain the version of the frontend they were originally provisioned with. Only newly provisioned tenants will receive the updated base bundle.*

### 2. Updating the Provisioning Pipeline (Python/AWS SAM)
If you make changes to the actual cloning logic (Lambdas, Step Functions, or Provisioners) located in `aws-marketplace-soft-launch/cloning-platform/`, you need to deploy the infrastructure updates via AWS SAM:

```bash
cd aws-marketplace-soft-launch/cloning-platform
sam build
sam deploy --no-confirm-changeset
```

### 3. Updating the SaaS Landing Page
If you make changes to the HTML/CSS of the Landing Page located in `aws-marketplace-soft-launch/Saas_Landing_Page/`, you can sync those changes directly to the public hosting bucket:

```bash
cd aws-marketplace-soft-launch/Saas_Landing_Page
aws s3 sync . s3://catalyst-saas-landing-eu-central-1/ --region eu-central-1 --exclude ".*"
```

## 🏗️ Architecture Overview

The core of this repository is an AWS Step Functions state machine (`CloningStateMachine`) driven by Python Lambda functions (`PipelineWorkerFunction`).

The state machine executes the following steps in order for every tenant:
1. **ProvisionDynamoDB:** Clones necessary tables.
2. **ProvisionSeed:** Injects base configurations.
3. **ProvisionSecrets:** Generates API keys.
4. **ProvisionCognito:** Creates the tenant User Pool and App Client.
5. **ProvisionAppSync:** Clones GraphQL APIs.
6. **ProvisionLambdas:** Wires up backend compute.
7. **ProvisionApiGateway:** Exposes REST endpoints.
8. **ProvisionAssessFrontend:** Creates an S3 bucket, copies the base Assess bundle, and injects runtime config.
9. **ProvisionAmplify:** Creates a new GitHub branch for the tenant and triggers an Amplify deployment for the Staff Portal.
10. **GenerateReport:** Compiles all endpoints/credentials and fires an SNS notification.
