import os
import base64
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CREDENTIALS_FILE = "credentials.json"  # must be in project root


def token_file_for(user_email):
    """Token file is unique per user Gmail."""
    sanitized = user_email.replace("@", "_at_").replace(".", "_")
    return f"token_{sanitized}.json"


def get_gmail_service(user_email: str):
    """
    Returns a Gmail service instance authenticated AS the user_email.
    If first-time → triggers OAuth browser login automatically.
    """
    TOKEN_FILE = token_file_for(user_email)

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # If no valid creds → OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Refresh silently
            creds.refresh(Request())
        else:
            # On local Mac this opens a browser window
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            try:
                creds = flow.run_local_server(port=0)
            except:
                # fallback (terminal copy/paste)
                creds = flow.run_console()

            # Save new token
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def send_email(subject, body, to_email, sender_email):
    """
    Sends an email FROM sender_email TO to_email.
    Requires OAuth token_<sender>.json
    """
    service = get_gmail_service(sender_email)

    message = MIMEText(body)
    message["to"] = to_email
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    return service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
