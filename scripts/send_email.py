"""Send HTML email via SMTP (Gmail).

Replaces dawidd6/action-send-mail which fails on large HTML bodies
due to Node argument length limits.
"""
from __future__ import annotations

import argparse
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", required=True)
    parser.add_argument("--from", dest="from_addr", default="박기영")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--html-file", required=True)
    args = parser.parse_args()

    user = os.environ["EMAIL_USER"]
    password = os.environ["EMAIL_PASS"]

    with open(args.html_file, encoding="utf-8") as f:
        html_body = f.read()

    msg = MIMEMultipart("alternative")
    msg["From"] = args.from_addr
    msg["To"] = args.to
    msg["Subject"] = args.subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(user, password)
        server.sendmail(user, args.to, msg.as_string())

    print(f"Email sent to {args.to}")


if __name__ == "__main__":
    main()
