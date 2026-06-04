from __future__ import annotations

import os
import platform
import shutil
import smtplib
import ssl
import subprocess
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

from PIL import Image


DEFAULT_SENDER = "alexhoffmann07@gmail.com"


def _applescript_string(value: str | Path) -> str:
    text = str(value)
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def read_recipients(path: Path) -> list[str]:
    if not path.exists():
        return ["alexhoffmann07@gmail.com"]
    recipients: list[str] = []
    for line in path.read_text().splitlines():
        clean = line.strip()
        if clean and not clean.startswith("#"):
            recipients.append(clean)
    return recipients or ["alexhoffmann07@gmail.com"]


def crop_header_strip(png_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(png_path) as img:
        width, _height = img.size
        crop = img.crop((0, 0, width, 270))
        crop.save(output_path)


def build_email(
    *,
    week: str,
    recipients: list[str],
    pdf_path: Path,
    full_png_path: Path,
    header_png_path: Path,
    sender: str | None = None,
) -> EmailMessage:
    subject = f"DOE Summary W/E {week}"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender or os.environ.get("DOE_SUMMARY_EMAIL_FROM", DEFAULT_SENDER)
    msg["To"] = ", ".join(recipients)
    msg.set_content(
        f"DOE Weekly Summary W/E {week}\n\n"
        "The dashboard PDF is attached.\n"
    )
    html = f"""\
<html>
  <body style="font-family:Arial,Helvetica,sans-serif;">
    <p>DOE Weekly Summary W/E {week}.</p>
    <p>The dashboard PDF is attached.</p>
  </body>
</html>
"""
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name)
    return msg


def write_eml(msg: EmailMessage, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(msg.as_bytes(policy=SMTP))


def send_smtp(msg: EmailMessage, recipients: list[str]) -> None:
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise RuntimeError("SMTP_HOST is not configured")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    sender = msg["From"]
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context) as smtp:
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg, from_addr=sender, to_addrs=recipients)
    else:
        with smtplib.SMTP(host, port) as smtp:
            smtp.starttls(context=context)
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg, from_addr=sender, to_addrs=recipients)


def send_sendmail(msg: EmailMessage, recipients: list[str]) -> None:
    binary = shutil.which("sendmail")
    if not binary:
        raise RuntimeError("sendmail is not available")
    proc = subprocess.run([binary, "-t", "-oi"], input=msg.as_bytes(policy=SMTP), check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"sendmail failed with exit code {proc.returncode}")


def create_apple_mail_draft(*, recipients: list[str], subject: str, html_path: Path, pdf_path: Path) -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("Apple Mail draft mode is only available on macOS")
    recipient_lines = "\n".join(
        f"make new to recipient at end of to recipients with properties {{address:{_applescript_string(r)}}}"
        for r in recipients
    )
    script = f'''
set htmlFile to POSIX file {_applescript_string(html_path)}
set pdfFile to POSIX file {_applescript_string(pdf_path)}
set htmlBody to read htmlFile
tell application "Mail"
    set newMessage to make new outgoing message with properties {{subject:{_applescript_string(subject)}, content:htmlBody, visible:true}}
    tell newMessage
        {recipient_lines}
        make new attachment with properties {{file name:pdfFile}} at after last paragraph
    end tell
    activate
end tell
'''
    proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Apple Mail draft creation failed")


def send_apple_mail(*, recipients: list[str], subject: str, week: str, pdf_path: Path) -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("Apple Mail send mode is only available on macOS")
    recipient_lines = "\n".join(
        f"make new to recipient at end of to recipients with properties {{address:{_applescript_string(r)}}}"
        for r in recipients
    )
    body = (
        f"DOE Weekly Summary W/E {week}\n\n"
        "The dashboard PDF is attached."
    )
    script = f'''
set pdfFile to POSIX file {_applescript_string(pdf_path)}
tell application "Mail"
    set newMessage to make new outgoing message with properties {{subject:{_applescript_string(subject)}, content:{_applescript_string(body)}, visible:false}}
    tell newMessage
        {recipient_lines}
        make new attachment with properties {{file name:pdfFile}} at after last paragraph
        send
    end tell
end tell
'''
    proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Apple Mail send failed")


def create_outlook_draft(*, recipients: list[str], subject: str, html_path: Path, pdf_path: Path) -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("Outlook draft mode is only available on macOS in this script")
    to_value = "; ".join(recipients)
    recipient_properties = "{email address:{address:" + _applescript_string(to_value) + "}}"
    script = f'''
set htmlFile to POSIX file {_applescript_string(html_path)}
set pdfPath to {_applescript_string(pdf_path)}
set htmlBody to read htmlFile
tell application "Microsoft Outlook"
    set newMessage to make new outgoing message with properties {{subject:{_applescript_string(subject)}, content:htmlBody}}
    tell newMessage
        make new recipient at end of to recipients with properties {recipient_properties}
        make new attachment with properties {{file:pdfPath}}
        open
    end tell
    activate
end tell
'''
    proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Outlook draft creation failed")


def write_email_html(*, week: str, header_png_path: Path, full_png_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = f"""\
<html>
  <body style="font-family:Arial,Helvetica,sans-serif;">
    <p>DOE Weekly Summary W/E {week}.</p>
    <p>The dashboard PDF is attached.</p>
  </body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def try_send(msg: EmailMessage, recipients: list[str], modes: list[str]) -> str:
    errors: list[str] = []
    for mode in modes:
        try:
            if mode == "smtp":
                send_smtp(msg, recipients)
            elif mode == "sendmail":
                send_sendmail(msg, recipients)
            else:
                raise RuntimeError(f"unsupported email mode: {mode}")
            return mode
        except Exception as exc:  # noqa: BLE001 - collect fallback errors for CLI output
            errors.append(f"{mode}: {exc}")
    raise RuntimeError("; ".join(errors))
