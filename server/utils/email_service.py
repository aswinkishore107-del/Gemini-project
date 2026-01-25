import smtplib
from email.message import EmailMessage
import os

COMPANY_NAME = "ABC Technologies"
TEST_NAME = "Online Hiring Assessment"

def send_pin_email(to_email, pin, start_time, end_time):
    msg = EmailMessage()

    msg["Subject"] = "Your Hiring Test Invitation"
    msg["From"] = os.getenv("SENDER_EMAIL")
    msg["To"] = to_email

    msg.set_content(f"""
Hi {to_email},

You have been invited to attend an online hiring assessment conducted by {COMPANY_NAME}.

Assessment Details:

Company Name      : {COMPANY_NAME}
Assessment Name   : {TEST_NAME}

Test Start Time   : {start_time} IST
Test End Time     : {end_time} IST

Login Instructions:
1. Open the test portal at the scheduled time.
2. Enter your Test PIN to begin the assessment.
3. The test is accessible only within the given time window.

Test Link:
http://127.0.0.1:5500/client/public/index.html


Your Test PIN: {pin}

Important Notes:
- The test will automatically close at the end time.
- If you do not submit before the end time, your attempt will be marked as Rejected.
- No autosave is available after time expiry.

Best of luck!

Regards,  
Recruitment Team  
{COMPANY_NAME}
""")

    with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT"))) as server:
        server.starttls()
        server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
        server.send_message(msg)
