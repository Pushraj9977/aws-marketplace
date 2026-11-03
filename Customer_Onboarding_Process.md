# AWS Marketplace Integration — Customer Onboarding Process

## 1. Overview
This document describes the end-to-end process by which a customer purchases the Assess and Encourage product via AWS Marketplace and receives a fully provisioned, dedicated instance of the platform.

- **Hosting account:** AWS Account 215116348101
- **Supported region:** eu-central-1 (Frankfurt) — currently the only available region
- **Products provisioned:** Assess (customer-facing web application) and Encourage (staff portal)

## 2. Customer Registration Flow

### 2.1 Purchase
The customer initiates the process by purchasing the product listing on AWS Marketplace.

### 2.2 Registration Form
Upon completing the purchase, the customer is presented with a registration form to capture the details required to provision their environment:

| Field | Description |
| :--- | :--- |
| **Company Name** | Name of the purchasing company |
| **Contact Name** | Primary contact at the customer company |
| **Contact Phone Number** | Phone number for the customer contact |
| **Super User Email** | Email address for the account that will manage access and configuration; a temporary password is sent here once the deployment is ready |
| **AWS Region** | Region where the application will reside (currently limited to eu-central-1, Frankfurt); customers should consider data residency requirements |

### 2.3 Registration Confirmation
After submitting the form, the customer receives an on-screen confirmation notifying them that registration was successful, that deployment may take up to two hours, and that deployment details will be sent to the email address provided. The notification also includes a support link to the Jira Service Desk portal for raising tickets related to deployment issues.

## 3. Backend Provisioning Process

### 3.1 Data Capture
Upon registration, customer details are written as a new entry to the `MarketplaceSubscribers` DynamoDB table with the following schema:

| Attribute | Description |
| :--- | :--- |
| `regToken` | Unique registration token (e.g., AMZ-xxx) |
| `awsRegion` | Selected AWS region |
| `companyName` | Customer company name |
| `contactEmail` | Contact email address |
| `contactPerson` | Contact name |
| `contactPhone` | Contact phone number |
| `createdAt` | Timestamp of registration (ISO 8601) |

### 3.2 Automated Provisioning
The new DynamoDB entry triggers an automated script that provisions a dedicated instance for the customer by cloning the following resources from the default instance:
- GitHub branch for Assess
- GitHub branch for Encourage
- Lambda functions
- DynamoDB tables
- S3 buckets

### 3.3 Deployment
Once cloning is complete, two AWS Amplify deployments are built: one for Assess and one for Encourage.

### 3.4 Super User Creation
Following successful deployment, a super user account is created for the Encourage staff portal using the email address supplied during registration.

## 4. Customer Notification
Once provisioning is complete, the customer receives an email (sent via Amazon SES) containing:
- Link to the Encourage staff portal
- Super user email and temporary password
- Link to the Assess web application
- Support contact link (Jira Service Desk portal)

**Sample Notification Email**
> Dear [Customer],
> 
> Congratulations, your SaaS deployment is ready! Here is the required information:
> 
> **Staff Portal:** [Encourage Link]
> **Super User Email:** [super user email]
> **Password:** [super user password]
> **Web Application:** [Assess Link]
> 
> If you have any questions, please contact us through the following link: [Support Portal](https://actint.atlassian.net/servicedesk/customer/portal/4)

## 5. Support
All post-deployment support requests are routed through the Jira Service Desk customer portal: [https://actint.atlassian.net/servicedesk/customer/portal/4](https://actint.atlassian.net/servicedesk/customer/portal/4)

---
*Note: Values shown in this document (e.g., registration tokens, sample credentials, contact details) are illustrative test data only and must not be treated as production credentials.*

*CONFIDENTIAL – All rights reserved. Alliance Care Technologies International Limited.*
