"""Generate AWS Frankfurt Resource Report as a .docx file."""
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import datetime

doc = Document()

# ── Page margins ──────────────────────────────────────────────────────────────
for section in doc.sections:
    section.top_margin    = Inches(0.8)
    section.bottom_margin = Inches(0.8)
    section.left_margin   = Inches(1.0)
    section.right_margin  = Inches(1.0)

# ── Helper: shade table header row ───────────────────────────────────────────
def shade_row(row, hex_color="1F4E79"):
    for cell in row.cells:
        tc   = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd  = OxmlElement("w:shd")
        shd.set(qn("w:val"),   "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"),  hex_color)
        tcPr.append(shd)

def style_header_cell(cell, text):
    cell.text = text
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.runs[0]
    run.bold = True
    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    run.font.size = Pt(9)

def add_table_row(table, *values):
    row = table.add_row()
    for i, v in enumerate(values):
        row.cells[i].text = str(v)
        row.cells[i].paragraphs[0].runs[0].font.size = Pt(9)
    return row

# ─────────────────────────────────────────────────────────────────────────────
# TITLE
# ─────────────────────────────────────────────────────────────────────────────
title = doc.add_heading("AWS Resource Report", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
title.runs[0].font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)

sub = doc.add_paragraph()
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = sub.add_run(f"Region: eu-central-1 (Frankfurt)  |  Account: 215116348101  |  Generated: {datetime.date.today()}")
r.font.size = Pt(10)
r.font.color.rgb = RGBColor(0x44, 0x44, 0x44)
doc.add_paragraph()

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY BOX
# ─────────────────────────────────────────────────────────────────────────────
doc.add_heading("Summary", level=1)
summary_data = [
    ("Lambda Functions",      "36"),
    ("DynamoDB Tables",        "46"),
    ("REST APIs (v1)",         "18"),
    ("HTTP APIs (v2)",          "3"),
    ("Cognito User Pools",      "3"),
    ("Secrets Manager",         "0"),
    ("Amplify Apps",            "3"),
    ("S3 Buckets",             "34"),
    ("IAM Roles",              "90"),
    ("CloudWatch Log Groups",  "26"),
]
tbl = doc.add_table(rows=1, cols=2)
tbl.style = "Table Grid"
shade_row(tbl.rows[0])
style_header_cell(tbl.rows[0].cells[0], "Service")
style_header_cell(tbl.rows[0].cells[1], "Count")
for name, count in summary_data:
    add_table_row(tbl, name, count)
doc.add_paragraph()

# ─────────────────────────────────────────────────────────────────────────────
# 1. LAMBDA FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────
doc.add_heading("1. Lambda Functions (36)", level=1)
lambdas = [
    ("act-secure-watcher-auth-3",           "python3.11", "256 MB", "15s"),
    ("act-secure-watcher-connector-3",       "python3.11", "256 MB", "30s"),
    ("act-secure-watcher-processor-3",       "python3.11", "512 MB", "60s"),
    ("act-secure-watcher-report-delivery",   "python3.11", "128 MB", "30s"),
    ("act-secure-watcher-upload-3",          "python3.11", "512 MB", "30s"),
    ("amplify-catalysthealthyag-UpdateRolesWithIDPFuncti-8QRghrN43vBy", "nodejs22.x", "128 MB", "300s"),
    ("amplify-catalysthealthyag-UpdateRolesWithIDPFuncti-jPtFRz3jQTxS", "nodejs22.x", "128 MB", "300s"),
    ("amplify-catalysthealthyag-UpdateRolesWithIDPFuncti-MylD3VKnyWY9", "nodejs22.x", "128 MB", "300s"),
    ("backendApi-bernadene",                 "nodejs18.x", "128 MB", "25s"),
    ("backendApi-cinda",                     "nodejs18.x", "128 MB", "25s"),
    ("backendApi-dev",                       "nodejs18.x", "128 MB", "25s"),
    ("bhaSession-bernadene",                 "nodejs18.x", "128 MB", "25s"),
    ("bhaSession-cinda",                     "nodejs18.x", "128 MB", "25s"),
    ("bhaSession-dev",                       "nodejs18.x", "128 MB", "25s"),
    ("engageapi-bernadene",                  "nodejs18.x", "128 MB", "25s"),
    ("engageapi-cinda",                      "nodejs18.x", "128 MB", "25s"),
    ("engageapi-dev",                        "nodejs18.x", "128 MB", "25s"),
    ("firebaseTrigger-bernadene",            "nodejs18.x", "128 MB", "25s"),
    ("firebaseTrigger-cinda",                "nodejs18.x", "128 MB", "25s"),
    ("firebaseTrigger-dev",                  "nodejs18.x", "128 MB", "25s"),
    ("health-api-fetch",                     "python3.12", "128 MB", "30s"),
    ("HealthApiLambda",                      "python3.12", "128 MB", "15s"),
    ("HealthIngestionLambda",                "python3.12", "128 MB", "15s"),
    ("health-sqs-to-dynamo",                 "python3.12", "128 MB", "30s"),
    ("intern-saveData",                      "nodejs24.x", "128 MB", "303s"),
    ("MarketplaceSubscriberHandler",         "nodejs20.x", "128 MB", "10s"),
    ("membershipScheduler-bernadene",        "nodejs18.x", "128 MB", "25s"),
    ("membershipScheduler-cinda",            "nodejs18.x", "128 MB", "25s"),
    ("membershipScheduler-dev",              "nodejs18.x", "128 MB", "25s"),
    ("sendEventReminderNotification",        "nodejs24.x", "128 MB", "3s"),
    ("staffApi-bernadene",                   "nodejs18.x", "128 MB", "300s"),
    ("staffApi-cinda",                       "nodejs18.x", "128 MB", "25s"),
    ("staffApi-dev",                         "nodejs18.x", "128 MB", "300s"),
    ("webhook-bernadene",                    "nodejs18.x", "128 MB", "25s"),
    ("webhook-cinda",                        "nodejs18.x", "128 MB", "25s"),
    ("webhook-dev",                          "nodejs18.x", "128 MB", "25s"),
]
t = doc.add_table(rows=1, cols=4)
t.style = "Table Grid"
shade_row(t.rows[0])
for h, col in zip(["Function Name","Runtime","Memory","Timeout"], t.rows[0].cells):
    style_header_cell(col, h)
for row in lambdas:
    add_table_row(t, *row)
doc.add_paragraph()

# ─────────────────────────────────────────────────────────────────────────────
# 2. DYNAMODB TABLES
# ─────────────────────────────────────────────────────────────────────────────
doc.add_heading("2. DynamoDB Tables (46)", level=1)
tables = [
    "act-secure-parsed-reports",              "act-secure-parsed-reports-3",
    "act-secure-report-delivery-logs-3",      "act-secure-watcher-report-delivery-logs",
    "act-secure-webhook-payloads",            "act-secure-webhook-payloads-3",
    "act-store-customer-mapping",             "act-store-customer-mapping-3",
    "Attend-3gqmivv4fje2zdutbvfdkgdrmm-dev", "Attend-uqcdlcixrfhpvlcslxgrpqvaz4-cinda",
    "Attend-uyxbz2ndazh7jjioeimk3ctuqq-bernadene", "AwsHealthEvents",
    "Catalyst_CompConfig",                    "CatalystEngageBHAResults",
    "CatalystEngageContactUstable",           "catEncounter_Dashboard_MessageBoard",
    "catEncounter_Event_Table",               "catEncounter_Membership_Table",
    "CatEncounter_RecommendedEvent",          "catEncounter_StaffTable",
    "CatEncounter_Users_Table",               "catEncourageStaffAssignments",
    "CheckIn_Table",                          "Event_Landing_Notes",
    "FeelingMeter",                           "FibriCheck_Prescriptions_Table",
    "FibriCheck_User_Table",                  "HeartRhythm_Prescriptions_History_Table",
    "HeartRhythm_Prescriptions_Table",        "HeartRhythm_Results_Table",
    "Heart_Rhythm_Transaction_Log",           "HeartRhythm_User_Table",
    "LocalHealthEvents",                      "MarketplaceSubscribers",
    "memberAssessments",                      "Member_Landing_Notes",
    "memberPlans",                            "Messages-3gqmivv4fje2zdutbvfdkgdrmm-dev",
    "Messages-uqcdlcixrfhpvlcslxgrpqvaz4-cinda", "Messages-uyxbz2ndazh7jjioeimk3ctuqq-bernadene",
    "Picture_Table",                          "SecureDataConnectFacilities",
    "SecureDataConnectFacilities-3",          "StaffCheckIn_Table",
    "Staff_Landing_Notes",                    "Thought_Table",
]
t = doc.add_table(rows=1, cols=2)
t.style = "Table Grid"
shade_row(t.rows[0])
style_header_cell(t.rows[0].cells[0], "#")
style_header_cell(t.rows[0].cells[1], "Table Name")
for i, name in enumerate(tables, 1):
    add_table_row(t, str(i), name)
doc.add_paragraph()

# ─────────────────────────────────────────────────────────────────────────────
# 3. API GATEWAY
# ─────────────────────────────────────────────────────────────────────────────
doc.add_heading("3. API Gateway — REST APIs v1 (18)", level=1)
rest_apis = [
    ("0j48f3mayg", "act-secure-report-delivery-apigw-3"),
    ("097s770sac", "backendApi (bernadene)"),
    ("0thizvg0q4", "backendApi (cinda)"),
    ("esjiak8rfe", "backendApi (dev)"),
    ("97a7sz4dz6", "bhaSession (bernadene)"),
    ("e3w6vikzb7", "bhaSession (cinda)"),
    ("qhvwc28krb", "bhaSession (dev)"),
    ("648ttjnrok", "engageapi (bernadene)"),
    ("gglgqcaplf", "engageapi (cinda)"),
    ("xf121hff8g", "engageapi (dev)"),
    ("m7gj3gbagk", "MarketplaceSubscriberApi"),
    ("zt47qmyhg7", "Secure-Watcher-Report-Webhook-API"),
    ("ibdgfwh94d", "staffApi (bernadene)"),
    ("ji8d3icjqg", "staffApi (cinda)"),
    ("y31kkaqup7", "staffApi (dev)"),
    ("at8xiu2jre", "webhook (bernadene)"),
    ("lyqy93qmol", "webhook (cinda)"),
    ("zvxyjpcm0d", "webhook (dev)"),
]
t = doc.add_table(rows=1, cols=2)
t.style = "Table Grid"
shade_row(t.rows[0])
style_header_cell(t.rows[0].cells[0], "API ID")
style_header_cell(t.rows[0].cells[1], "Name")
for row in rest_apis:
    add_table_row(t, *row)

doc.add_paragraph()
doc.add_heading("4. API Gateway — HTTP APIs v2 (3)", level=1)
http_apis = [
    ("pity9w2qf3", "HealthAPI"),
    ("amjyutc4ye", "HealthDashboardAPI"),
    ("jn1c69qblh", "HealthDashboardAPI"),
]
t = doc.add_table(rows=1, cols=2)
t.style = "Table Grid"
shade_row(t.rows[0])
style_header_cell(t.rows[0].cells[0], "API ID")
style_header_cell(t.rows[0].cells[1], "Name")
for row in http_apis:
    add_table_row(t, *row)
doc.add_paragraph()

# ─────────────────────────────────────────────────────────────────────────────
# 4. COGNITO
# ─────────────────────────────────────────────────────────────────────────────
doc.add_heading("5. Cognito User Pools (3)", level=1)
cognito = [
    ("catalysthealthyagingcd0f7d5d_userpool_cd0f7d5d-bernadene", "eu-central-1_MxfviYZRR", "2026-04-09"),
    ("catalysthealthyagingcd0f7d5d_userpool_cd0f7d5d-dev",       "eu-central-1_sqttUUuia", "2026-03-27"),
    ("catalysthealthyagingd8e0fa41_userpool_d8e0fa41-cinda",     "eu-central-1_QZYEbfvv4", "2026-04-01"),
]
t = doc.add_table(rows=1, cols=3)
t.style = "Table Grid"
shade_row(t.rows[0])
style_header_cell(t.rows[0].cells[0], "Pool Name")
style_header_cell(t.rows[0].cells[1], "Pool ID")
style_header_cell(t.rows[0].cells[2], "Created")
for row in cognito:
    add_table_row(t, *row)
doc.add_paragraph()

# ─────────────────────────────────────────────────────────────────────────────
# 5. AMPLIFY
# ─────────────────────────────────────────────────────────────────────────────
doc.add_heading("6. Amplify Apps & Branches (3 Apps)", level=1)
amplify = [
    ("Catalyst-HealthyAging",             "d246slprgvqfid", "WEB_COMPUTE", "medi-clinic-eu-central-1, medi-clinic, feature/fibricheck"),
    ("assess-medi-clinic-eu-central-1",   "d1pcxhvq2e48x2", "WEB",         "staging"),
    ("mediClinic",                        "d2fyag2c6a65eq", "WEB",         "— (no branches)"),
]
t = doc.add_table(rows=1, cols=4)
t.style = "Table Grid"
shade_row(t.rows[0])
style_header_cell(t.rows[0].cells[0], "App Name")
style_header_cell(t.rows[0].cells[1], "App ID")
style_header_cell(t.rows[0].cells[2], "Platform")
style_header_cell(t.rows[0].cells[3], "Branches")
for row in amplify:
    add_table_row(t, *row)
doc.add_paragraph()

# ─────────────────────────────────────────────────────────────────────────────
# 6. S3 BUCKETS
# ─────────────────────────────────────────────────────────────────────────────
doc.add_heading("7. S3 Buckets (34)", level=1)
s3 = [
    ("acti-fallback-staff","2026-04-26"),
    ("amplify-catalysthealthyaging-audy-4253a-deployment","2026-03-13"),
    ("amplify-catalysthealthyaging-bernadene-1d6ab-deployment","2026-04-30"),
    ("amplify-catalysthealthyaging-beverie-220ee-deployment","2026-03-11"),
    ("amplify-catalysthealthyaging-brandea-de2cc-deployment","2026-03-11"),
    ("amplify-catalysthealthyaging-cinda-ca46a-deployment","2026-04-29"),
    ("amplify-catalysthealthyaging-clementine-647c2-deployment","2026-03-11"),
    ("amplify-catalysthealthyaging-dev-5a4d9-deployment","2026-04-29"),
    ("amplify-catalysthealthyaging-fernanda-49ebd-deployment","2026-03-11"),
    ("amplify-catalysthealthyaging-ivett-fef28-deployment","2026-03-11"),
    ("amplify-catalysthealthyaging-jerry-4d7b6-deployment","2025-11-06"),
    ("amplify-catalysthealthyaging-lyda-52f45-deployment","2026-03-11"),
    ("amplify-catalysthealthyaging-mediclinic-3f5cb-deployment","2026-03-11"),
    ("amplify-catalysthealthyaging-mikaela-7e904-deployment","2026-03-11"),
    ("amplify-catalysthealthyaging-norine-35979-deployment","2026-03-11"),
    ("amplify-catalysthealthyaging-sande-dbfff-deployment","2026-03-11"),
    ("amplify-catalysthealthyaging-staging-74c69-deployment","2025-11-06"),
    ("amplify-catalysthealthyaging-ulla-70af8-deployment","2025-11-06"),
    ("amplify-mediclinic-dev-36d90-deployment","2026-04-30"),
    ("assess-demo-eu-west-1","2026-07-31"),
    ("aws-health-dashboard-23158504","2026-04-15"),
    ("aws-health-dashboard-305729","2026-04-15"),
    ("aws-health-dashboard-31706804","2026-04-15"),
    ("aws-health-dashboard-47721725","2026-04-15"),
    ("aws-health-dashboard-605140","2026-04-15"),
    ("aws-s3-dynamodb-backup","2026-04-29"),
    ("cf-templates-10z6d3pbtqxs5-me-central-1","2025-08-06"),
    ("frontend-app-eu-west-1-1784100277","2026-07-15"),
    ("healthy-aging-buckets-frankfurt","2026-06-29"),
    ("healthy-aging-buckets-test","2025-08-08"),
    ("healthy-aging-buckets-test-215116348101-eu-central-1-an","2026-03-31"),
    ("optain-picker-1-eu","2026-05-14"),
    ("optain-picker-1-eu-3","2026-07-09"),
    ("smartkablesai","2025-11-08"),
]
t = doc.add_table(rows=1, cols=2)
t.style = "Table Grid"
shade_row(t.rows[0])
style_header_cell(t.rows[0].cells[0], "Bucket Name")
style_header_cell(t.rows[0].cells[1], "Created")
for row in s3:
    add_table_row(t, *row)
doc.add_paragraph()

# ─────────────────────────────────────────────────────────────────────────────
# Footer note
# ─────────────────────────────────────────────────────────────────────────────
doc.add_paragraph()
note = doc.add_paragraph()
note.alignment = WD_ALIGN_PARAGRAPH.CENTER
nr = note.add_run(f"Generated by aws-frankfurt-report.sh | Account 215116348101 | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
nr.font.size = Pt(8)
nr.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

out = "Frankfurt_AWS_Resource_Report.docx"
doc.save(out)
print(f"Saved: {out}")
