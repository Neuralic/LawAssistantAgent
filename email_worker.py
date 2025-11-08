import imaplib
import email
import os
import time
import base64
from email.mime.text import MIMEText
from email.header import decode_header
from dotenv import load_dotenv
from pdf_processor import process_single_pdf
from grader import analyze_document
from grader_utils import write_result_to_file
from datetime import datetime, date, timedelta
import json
import traceback
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import re

load_dotenv()

# Gmail credentials for RECEIVING emails via IMAP
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS") or os.getenv("EMAIL_ADDRESS")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD") or os.getenv("EMAIL_PASSWORD")

# Gmail API credentials for SENDING emails - Manual Access Token
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
GMAIL_ACCESS_TOKEN = os.getenv("GMAIL_ACCESS_TOKEN")

FROM_NAME = "Financial Analyzer"

# Validate required environment variables
if not GMAIL_ADDRESS:
    raise ValueError("GMAIL_ADDRESS (or EMAIL_ADDRESS) environment variable is required")
if not GMAIL_PASSWORD:
    raise ValueError("GMAIL_PASSWORD (or EMAIL_PASSWORD) environment variable is required")
if not GMAIL_CLIENT_ID:
    raise ValueError("GMAIL_CLIENT_ID environment variable is required for Gmail API")
if not GMAIL_CLIENT_SECRET:
    raise ValueError("GMAIL_CLIENT_SECRET environment variable is required for Gmail API")
if not GMAIL_ACCESS_TOKEN:
    raise ValueError("GMAIL_ACCESS_TOKEN environment variable is required for Gmail API")

INCOMING_DIR = "incoming_pdfs"
os.makedirs(INCOMING_DIR, exist_ok=True)

print(f"[DEBUG] GMAIL_ADDRESS (for receiving): {GMAIL_ADDRESS}")
print(f"[DEBUG] Gmail API configured for sending with manual access token")

# Gmail API setup
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def get_gmail_service():
    """Get Gmail API service using manual access token"""
    try:
        # Build credentials directly from the access token
        creds = Credentials(
            token=GMAIL_ACCESS_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GMAIL_CLIENT_ID,
            client_secret=GMAIL_CLIENT_SECRET,
            scopes=SCOPES
        )
        
        # Test the credentials by building the service
        service = build('gmail', 'v1', credentials=creds)
        
        # Verify the token works by making a test call
        service.users().getProfile(userId='me').execute()
        
        print("[SUCCESS] ✅ Gmail API service initialized successfully with access token")
        return service
        
    except Exception as e:
        print(f"\n{'='*60}")
        print(f"[ERROR] ❌ Failed to initialize Gmail API service")
        print(f"{'='*60}")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {e}")
        print(f"\nPossible causes:")
        print(f"1. GMAIL_ACCESS_TOKEN has expired (tokens expire in ~1 hour)")
        print(f"2. Invalid or malformed access token")
        print(f"3. Token doesn't have required scopes")
        print(f"\nPlease generate a new access token and update the GMAIL_ACCESS_TOKEN environment variable.")
        print(f"{'='*60}\n")
        traceback.print_exc()
        raise SystemExit(f"Gmail API initialization failed: {e}")

# Initialize Gmail service - fail fast if token is invalid
try:
    gmail_service = get_gmail_service()
except SystemExit:
    print("\n[FATAL] Cannot continue without valid Gmail API credentials. Exiting.")
    exit(1)

# Document type detection helper
def detect_document_type(text):
    """Auto-detect financial document type from content"""
    text_lower = text.lower()
    if "bank statement" in text_lower or "account balance" in text_lower or "checking account" in text_lower:
        return "bank_statement"
    elif "credit report" in text_lower or "credit score" in text_lower or "fico" in text_lower or "experian" in text_lower:
        return "credit_report"
    else:
        return "generic"

def extract_email_address(sender_string):
    """Extract just the email address from a sender string like 'Name <email@example.com>'"""
    match = re.search(r'<(.+?)>', sender_string)
    if match:
        return match.group(1)
    return sender_string.strip()

def check_inbox_periodically():
    while True:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
            mail.select("inbox")

            # Calculate date for 24 hours ago
            date_24_hours_ago = (date.today() - timedelta(days=1)).strftime("%d-%b-%Y")
            
            # Search for unseen emails from the last 24 hours
            status, email_ids = mail.search(None, 
                                            f'(UNSEEN SENTSINCE "{date_24_hours_ago}")')
            
            email_list = email_ids[0].split()
            print(f"Found {len(email_list)} unseen emails from the last 24 hours.")
            
            for email_id in email_list:
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])

                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding or "utf-8")

                sender, encoding = decode_header(msg["From"])[0]
                if isinstance(sender, bytes):
                    sender = sender.decode(encoding or "utf-8")
                
                # Extract just the email address
                sender_email = extract_email_address(sender)

                print(f"[Financial Analyzer] Processing email from: {sender} (extracted: {sender_email}) with subject: {subject}")

                has_pdf_attachment = False
                for part in msg.walk():
                    try:
                        if part.get_content_maintype() == "application" and part.get_content_subtype() == "pdf":
                            has_pdf_attachment = True
                            filename = part.get_filename()
                            if filename:
                                filepath = os.path.join(INCOMING_DIR, filename)
                                print(f"Identified PDF attachment: {filename}. Saving to {filepath}")
                                with open(filepath, "wb") as f:
                                    f.write(part.get_payload(decode=True))
                                print(f"Downloaded PDF: {filename}")

                                # Process PDF, analyze document, and send email
                                process_and_respond(filepath, sender_email, subject)
                            else:
                                print("PDF attachment found but no filename.")
                    except AttributeError as ae:
                        print(f"AttributeError when processing email part: {ae}. Part type: {type(part)}")
                    except Exception as part_e:
                        print(f"Unexpected error when processing email part: {part_e}. Part type: {type(part)}")
                
                if not has_pdf_attachment:
                    print(f"No PDF attachment found in email from {sender_email} with subject: {subject}")

                # Mark as seen immediately
                mail.store(email_id, "+FLAGS", "\\Seen")

            mail.logout()

        except Exception as e:
            print(f"Error in email worker: {e}")
            traceback.print_exc()
        
        # Check every 30 seconds for swift response
        time.sleep(30)

def process_and_respond(pdf_path, recipient_email, original_subject):
    try:
        print(f"[Financial Analyzer] Processing PDF: {pdf_path}")
        extracted_text = process_single_pdf(pdf_path)
        print(f"[Financial Analyzer] Extracted text length: {len(extracted_text)}")
        
        # Auto-detect document type
        doc_type = detect_document_type(extracted_text)
        print(f"[Financial Analyzer] Detected document type: {doc_type}")
        
        # analyze_document returns a dictionary (JSON object)
        analysis_result = analyze_document(extracted_text, doc_type)
        
        # Check if analysis_result is an error dictionary
        if isinstance(analysis_result, dict) and "error" in analysis_result:
            print(f"[Financial Analyzer] Error during analysis: {analysis_result['error']}")
            error_msg_to_send = str(analysis_result["error"])
            send_email_error(recipient_email, original_subject, error_msg_to_send)
            return

        print(f"[Financial Analyzer] Analysis complete")

        # Transform the result to match frontend expectations
        frontend_result = {
            "name": analysis_result.get("client_name", "Unknown"),
            "email": recipient_email,
            "course": doc_type.replace("_", " ").title(),
            "grade_output": f"Assessment: {analysis_result.get('overall_assessment', 'Pending Review')}\n\nSummary: {analysis_result.get('analysis_summary', 'No summary available')}\n\nKey Findings: {analysis_result.get('key_findings', 'No findings')}\n\nRed Flags: {analysis_result.get('red_flags', 'None identified')}\n\nRecommendations: {analysis_result.get('recommendations', 'No recommendations')}",
            "timestamp": "",
            "criteria_scores": analysis_result.get("criteria_analysis", []),
            "document_type": doc_type,
            "red_flags": analysis_result.get("red_flags", "None identified")
        }

        # Save the structured result
        write_result_to_file(frontend_result)
        print(f"[Financial Analyzer] Analysis result saved.")

        # Format feedback for email - safely convert all values to strings
        feedback_for_email = f"FINANCIAL DOCUMENT ANALYSIS REPORT\n\n"
        feedback_for_email += f"Document Type: {doc_type.replace('_', ' ').upper()}\n"
        
        overall_assessment = analysis_result.get('overall_assessment', 'N/A')
        feedback_for_email += f"Overall Assessment: {str(overall_assessment)}\n\n"
        
        analysis_summary = analysis_result.get('analysis_summary', 'N/A')
        feedback_for_email += f"SUMMARY:\n{str(analysis_summary)}\n\n"
        
        key_findings = analysis_result.get('key_findings', 'N/A')
        feedback_for_email += f"KEY FINDINGS:\n{str(key_findings)}\n\n"
        
        # Add criteria analysis
        feedback_for_email += "DETAILED ANALYSIS:\n"
        for criterion in analysis_result.get("criteria_analysis", []):
            # Safely get findings and convert to string before replacing
            findings_raw = criterion.get("findings", "N/A")
            findings = str(findings_raw).replace("{", "{{").replace("}", "}}") if findings_raw else "N/A"
            
            assessment_raw = criterion.get("assessment", "N/A")
            assessment = str(assessment_raw) if assessment_raw else "N/A"
            
            notes_raw = criterion.get("notes", "")
            notes = str(notes_raw).replace("{", "{{").replace("}", "}}") if notes_raw else ""

            feedback_for_email += f"\n{criterion.get('criterion', 'N/A')}:\n"
            feedback_for_email += f"  Findings: {findings}\n"
            feedback_for_email += f"  Assessment: {assessment}\n"
            if notes:
                feedback_for_email += f"  Notes: {notes}\n"
        
        # Add red flags section - safely convert to string
        red_flags = analysis_result.get("red_flags", "None identified")
        red_flags_str = str(red_flags) if red_flags else "None identified"
        if red_flags_str and red_flags_str != "None identified":
            feedback_for_email += f"\n⚠️ RED FLAGS:\n{red_flags_str}\n"
        
        recommendations = analysis_result.get('recommendations', 'N/A')
        feedback_for_email += f"\nRECOMMENDATIONS:\n{str(recommendations)}\n"
        feedback_for_email += "\n---\nThis is an automated analysis. Please review the original document for complete details."

        send_email_feedback(recipient_email, original_subject, feedback_for_email)
        print(f"[Financial Analyzer] Analysis report sent to {recipient_email}")

    except Exception as e:
        print(f"Error processing and responding to PDF {pdf_path}: {e}")
        import traceback
        traceback.print_exc()
        error_msg_to_send = str(e)
        send_email_error(recipient_email, original_subject, error_msg_to_send)

def send_email_via_gmail_api(to_email, subject, body):
    """Send email using Gmail API"""
    try:
        print(f"\n{'='*60}")
        print(f"[Gmail API] Preparing to send email")
        print(f"{'='*60}")
        
        # Extract clean email
        clean_email = extract_email_address(to_email)
        
        print(f"[Gmail API] To: {clean_email}")
        print(f"[Gmail API] From: {FROM_NAME} <{GMAIL_ADDRESS}>")
        print(f"[Gmail API] Subject: {subject}")
        
        # Create message
        message = MIMEText(body)
        message['to'] = clean_email
        message['from'] = f"{FROM_NAME} <{GMAIL_ADDRESS}>"
        message['subject'] = subject
        
        # Encode message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        print(f"[Gmail API] Calling Gmail API send...")
        
        # Send via Gmail API
        send_message = gmail_service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()
        
        print(f"[Gmail API] ✅ Email sent successfully!")
        print(f"[Gmail API] Message ID: {send_message['id']}")
        print(f"{'='*60}\n")
        return True
        
    except Exception as e:
        print(f"\n{'='*60}")
        print(f"[Gmail API] ❌ Error sending email")
        print(f"{'='*60}")
        print(f"[Gmail API] Error type: {type(e).__name__}")
        print(f"[Gmail API] Error: {e}")
        
        # Check if it's an expired token error
        if "invalid_grant" in str(e) or "Invalid Credentials" in str(e):
            print(f"\n[Gmail API] ⚠️  ACCESS TOKEN HAS EXPIRED!")
            print(f"[Gmail API] Please generate a new access token and update GMAIL_ACCESS_TOKEN")
        
        traceback.print_exc()
        print(f"{'='*60}\n")
        return False

def send_email_feedback(recipient_email, original_subject, feedback):
    """Send analysis feedback email"""
    subject = f"Re: {original_subject} - Financial Document Analysis Report"
    
    success = send_email_via_gmail_api(recipient_email, subject, feedback)
    if success:
        print(f"[Financial Analyzer] Analysis report sent successfully")
    else:
        print(f"[Financial Analyzer] ❌ Failed to send analysis report")

def send_email_error(recipient_email, original_subject, error_message):
    """Send error notification email"""
    error_body = f"An error occurred while processing your financial document (Subject: {original_subject}):\n\n{error_message}\n\nPlease ensure the document is a valid PDF and try again, or contact our support team."
    subject = f"Re: {original_subject} - Error Processing Document"
    
    success = send_email_via_gmail_api(recipient_email, subject, error_body)
    if success:
        print(f"[Financial Analyzer] Error notification sent successfully")
    else:
        print(f"[Financial Analyzer] ❌ Failed to send error notification")

if __name__ == "__main__":
    print("\n" + "="*60)
    print("[Financial Analyzer] Email worker started")
    print("="*60)
    print(f"Monitoring Gmail: {GMAIL_ADDRESS}")
    print(f"Sending via: Gmail API (Manual Access Token)")
    print(f"Check interval: 30 seconds")
    print(f"⚠️  Remember: Access tokens expire in ~1 hour")
    print("="*60 + "\n")
    check_inbox_periodically()
