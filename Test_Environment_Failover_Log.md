# Test Environment: CloudFront Failover Implementation Log

## 1. Objective
This document outlines the exact configuration, setup, and validation of the High Availability Failover architecture built in the AWS **test environment**. It serves as the proven blueprint for migrating the production domains to this architecture.

## 2. Test Environment Details
The test was conducted using a cross-account architecture to mirror the production setup.

*   **Test URL:** `https://testfailover.aoeg.io`
*   **Account A (DNS):** `613205425102`
*   **Account B (Infrastructure):** `215116348101`

### Infrastructure Components (Account B)
*   **CloudFront Distribution ID:** `ELK3H2E9F80EV` (Domain: `d3w04x3bhl2mlc.cloudfront.net`)
*   **SSL Certificate:** ACM Certificate in `us-east-1` for `testfailover.aoeg.io` (ARN: `...0b9c4ced91d5`)
*   **Primary Origin (Amplify):** `act-20260908-1.d246slprgvqfid.amplifyapp.com`
*   **Secondary Origin (S3 Fallback):** `fallback-tast` (Region: `eu-central-1`)

### DNS Configuration (Account A)
*   **Hosted Zone:** `aoeg.io`
*   **Record:** CNAME `testfailover.aoeg.io` pointing to `d3w04x3bhl2mlc.cloudfront.net` (with ACM DNS Validation records).

## 3. CloudFront Configuration Specs

### Origin Group (`FailoverOriginGroup`)
*   **Primary Origin ID:** `AmplifyOrigin`
*   **Secondary Origin ID:** `S3FallbackOrigin`
*   **Failover Criteria:** HTTP Status Codes `500`, `502`, `503`, `504`

### Cache Behavior & Headers
*   **Origin Request Policy:** `Managed-AllViewerExceptHostHeader`. This was critical to prevent AWS Amplify from rejecting the TLS connection via SNI mismatch.
*   **Viewer Request Function:** A CloudFront Function named `AddForwardedHost` was created and attached to the Default Cache Behavior. 
    *   **Code logic:** Extracts the Viewer `Host` header and injects `X-Forwarded-Host: testfailover.aoeg.io`.
    *   **Purpose:** Prevents the Next.js application from executing 307 absolute redirects to the raw `.amplifyapp.com` domain, masking the underlying infrastructure.

### Custom Error Responses
Configured to handle dynamic path requests during a failover (e.g. user requests `/dashboard` when S3 only has `index.html`):
1.  **Condition 1:** 403 Forbidden -> Rewrite path to `/index.html` -> Return `503 Service Unavailable`
2.  **Condition 2:** 404 Not Found -> Rewrite path to `/index.html` -> Return `503 Service Unavailable`

### S3 Security (OAC)
The `fallback-tast` S3 bucket was strictly kept private. **Origin Access Control (OAC)** was generated in CloudFront and attached to the S3 bucket policy, ensuring only the `ELK3H2E9F80EV` distribution could access the maintenance page.

---

## 4. Execution & Testing Log

### Test 1: Normal Operations & Header Fix
*   **Action:** Navigated to `https://testfailover.aoeg.io/`.
*   **Result:** The CloudFront Function successfully injected `X-Forwarded-Host`. The Next.js application loaded normally, and the URL remained completely stable on the custom domain without any `.amplifyapp.com` redirects. 
*   **Status:** ✅ SUCCESS

### Test 2: Triggering the Failover
*   **Action:** Intentionally "broke" the primary origin in CloudFront by changing the `AmplifyOrigin` Domain Name to a dead endpoint (`broken.example.com`). Wait for CloudFront deployment.
*   **Result:** CloudFront attempted to connect to the broken origin, timed out (502/504 error), and instantly triggered the Origin Group failover.
*   **Status:** ✅ SUCCESS

### Test 3: Verifying the Maintenance Page & Status Codes
*   **Action:** User refreshed `https://testfailover.aoeg.io/en`.
*   **Result:** The browser successfully displayed the S3 "Service Temporarily Unavailable" maintenance page. The URL in the address bar did not change. Background network checks confirmed the browser received a `503 Service Unavailable` response, ensuring SEO safety.
*   **Status:** ✅ SUCCESS

### Test 4: Application Recovery
*   **Action:** Restored the `AmplifyOrigin` Domain Name back to `act-20260908-1.d246slprgvqfid.amplifyapp.com` in CloudFront.
*   **Result:** Once deployed, CloudFront automatically resumed routing traffic to the healthy Amplify origin. The application came back online without any manual DNS intervention required.
*   **Status:** ✅ SUCCESS

## 5. Conclusion
The testing environment confirms that cross-account CloudFront Origin Groups, paired with Viewer Request functions and Custom Error Responses, effectively provide high-availability failover for Amplify-hosted Next.js applications without requiring DNS-level intervention.
