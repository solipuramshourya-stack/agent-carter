import base64
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def gmail_send_email(to_email: str, subject: str, body: str):
    """
    Sends an email using Gmail API with token.json authentication.
    Assumes credentials.json and token.json already exist.
    """

    # Load user credentials
    creds = Credentials.from_authorized_user_file(
        "token.json", 
        ["https://www.googleapis.com/auth/gmail.send"]
    )

    service = build("gmail", "v1", credentials=creds)

    message = MIMEText(body)
    message["to"] = to_email
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    send_result = service.users().messages().send(
        userId="me",
        body={"raw": raw}
    ).execute()

    return send_result
