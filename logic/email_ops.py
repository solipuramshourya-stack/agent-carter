import base64
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from logic.config import get_gmail_token_dict


def gmail_send_email(to_email: str, subject: str, body: str):

    token_info = get_gmail_token_dict()

    creds = Credentials.from_authorized_user_info(
        token_info,
        ["https://www.googleapis.com/auth/gmail.send"]
    )

    service = build("gmail", "v1", credentials=creds)

    # ---- Build email ----
    message = MIMEText(body)
    message["to"] = to_email
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    # ---- Send email ----
    result = service.users().messages().send(
        userId="me",
        body={"raw": raw}
    ).execute()

    return result
