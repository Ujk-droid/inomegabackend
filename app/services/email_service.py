"""Section 9.2 sending half — SMTP via Gmail App Password (stdlib smtplib, no
extra dependency). Pulled forward from the PDF/Email/WhatsApp dispatch block
because the Login Approval Gate (Section 3.1) and Forgot Password (Screen 1)
both need to send mail too.

GMAIL_APP_PASSWORD is still a placeholder in .env as of this build — every
call here will raise EmailDispatchError until real credentials are supplied.
Callers where email is a best-effort side channel (admin login-request
notifications, temp-password delivery) must catch and continue; callers where
email IS the feature (Section 9.2's explicit Share on Email) must let it
propagate as a real error to the caller.
"""

import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


class EmailDispatchError(Exception):
    """Raised when the SMTP send itself fails — auth error, network error, or
    (today) GMAIL_APP_PASSWORD still being the .env placeholder value."""


def send_email(to_email: str, subject: str, body: str, attachment: tuple[str, bytes] | None = None) -> None:
    """attachment, if given, is (filename, bytes) — e.g. an invoice PDF."""
    if not settings.gmail_user or not settings.gmail_app_password:
        raise EmailDispatchError("GMAIL_USER/GMAIL_APP_PASSWORD not configured yet")

    message = MIMEMultipart()
    message["From"] = settings.gmail_user
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    if attachment is not None:
        filename, content = attachment
        part = MIMEApplication(content, Name=filename)
        part["Content-Disposition"] = f'attachment; filename="{filename}"'
        message.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(settings.gmail_user, settings.gmail_app_password)
            server.sendmail(settings.gmail_user, [to_email], message.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailDispatchError(str(exc)) from exc


def send_login_request_notification(admin_email: str, staff_name: str) -> None:
    send_email(
        admin_email,
        "Omega Scales — Staff login awaiting your approval",
        f"{staff_name} is trying to log in and needs an Admin to approve it. "
        f"Open Login Approvals to Approve or Reject.",
    )


def send_temp_password_email(user_email: str, full_name: str, temp_password: str) -> None:
    send_email(
        user_email,
        "Omega Scales — Your account has been created",
        f"Hi {full_name},\n\nAn Admin created an Omega Scales account for you.\n\n"
        f"Email: {user_email}\nTemporary password: {temp_password}\n\n"
        f"Please log in and note this password is temporary.",
    )


def send_human_gate_pending_notification(admin_email: str, invoice_no: str | None, total_amount: float) -> None:
    send_email(
        admin_email,
        "Omega Scales — Invoice awaiting your approval",
        f"Invoice #{invoice_no or '(unassigned)'} for Rs. {total_amount:,.2f} exceeds the Human Gate threshold "
        f"and is waiting for Admin approval before it can be emailed or shared.",
    )


def send_password_reset_email(user_email: str, reset_token: str) -> None:
    reset_url = f"{settings.fastapi_backend_url}/api/v1/auth/reset-password/{reset_token}"
    send_email(
        user_email,
        "Omega Scales — Password reset requested",
        f"A password reset was requested for this account. This link expires in 1 hour:\n{reset_url}\n\n"
        f"If you didn't request this, you can ignore this email.",
    )
