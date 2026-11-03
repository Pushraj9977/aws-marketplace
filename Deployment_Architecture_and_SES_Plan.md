# Catalyst Provisioning: Deployment Architecture & SES Integration Plan

This document outlines the current state of the automated multi-tenant provisioning pipeline and the proposed plan to integrate AWS SES for automated customer welcome emails.

---

## 1. Current Architecture (Fully Automated Provisioning)

The multi-tenant cloning pipeline currently operates as a fully automated AWS Step Functions state machine. When a customer registers via the SaaS Landing Page (with a valid Marketplace token or a `test-` bypass token), the following happens without any manual intervention:

1. **DynamoDB, Cognito, & Secrets:** The pipeline spins up isolated DynamoDB tables, a dedicated Cognito User Pool, and generates unique API keys in Secrets Manager.
2. **AppSync & APIs:** The GraphQL and REST API endpoints are cloned and wired up to the tenant's new isolated database.
3. **S3 Frontend (Catalyst Assess):** 
   - A dedicated S3 bucket is created for the tenant.
   - Pre-compiled React assets are copied from the "Base Assets" bucket.
   - A dynamic `config.js` is generated and injected, ensuring the React app (`index.tsx`) uses the tenant's unique APIs and Cognito IDs instead of hardcoded variables.
4. **Amplify Frontend (Staff Portal):** A new GitHub branch is created for the tenant, and AWS Amplify is triggered to build the Next.js app using injected environment variables.
5. **Completion:** An internal AWS SNS notification is sent to the admin/DevOps team.

---

## 2. Proposed Feature: AWS SES Customer Welcome Emails

Currently, the customer does not receive their credentials automatically; they must be manually retrieved by an admin from AWS Secrets Manager. 
We propose integrating **AWS SES (Simple Email Service)** into the final `GenerateReport` stage of the pipeline to automatically dispatch a branded HTML welcome email directly to the customer.

### Why AWS SES?
- **Professional Formatting:** Unlike AWS SNS (which sends raw text alerts), SES allows us to send rich, beautifully formatted HTML emails.
- **Custom Branding:** We can send the email from a professional domain address (e.g., `no-reply@alliancecaretech.com`).
- **Direct Delivery:** The email can include a direct clickable link to their new Assess app alongside their temporary password.

### Implementation Steps

#### Step 1: AWS Infrastructure Updates
- **Permissions:** Grant the `ses:SendEmail` IAM permission to the `ReportGeneratorFunction` role inside the SAM `template.yaml`.
- **Configuration:** Add an environment variable (e.g., `SES_SENDER_EMAIL`) to define the verified "From" address.

#### Step 2: Python Code Updates (`report_generator.py`)
- Inject a new helper function: `_send_customer_welcome_email(env: EnvironmentModel)`
- **Fetch Credentials:** Use the AWS Secrets Manager API to dynamically retrieve the customer's plain-text temporary password from their generated `admin-bootstrap` secret.
- **HTML Template:** Construct a professional HTML email template that dynamically populates:
  - `{{company_name}}`
  - `{{assess_app_url}}`
  - `{{admin_email}}`
  - `{{temporary_password}}`
- **Dispatch:** Use the `boto3` SES client to send the email to the customer's registered email address.

### Requirements from the Team
1. **Verified Sender Address:** Before this code can be deployed, the team must log into the AWS Console, navigate to AWS SES, and verify the email address they wish to use as the sender (e.g., `welcome@alliancecaretech.com`). 
2. *(Optional)* **Sandbox Removal:** If the AWS account is currently in the SES Sandbox, a support ticket must be submitted to AWS to request production access; otherwise, SES will only be allowed to send emails *to* verified internal team addresses.
