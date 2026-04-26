import base64
import json
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import streamlit as st


def gmail_send_email(to_email: str, subject: str, body: str):

    # LOAD JSON CREDENTIALS FROM SECRETS
    token_info = json.loads(st.secrets["GMAIL_TOKEN"])

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
