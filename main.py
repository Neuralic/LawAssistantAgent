import imaplib
import email
import os
import time
import smtplib
from email.mime.text import MIMEText
from email.header import decode_header
from dotenv import load_dotenv
from pdf_processor import process_single_pdf
from grader import analyze_document
from grader_utils import write_result_to_file
from datetime import datetime, date, timedelta
import json
import traceback
import sys

load_dotenv()

EMAIL = os.getenv("EMAIL_ADDRESS")
PASSWORD = os.getenv("EMAIL_PASSWORD")
INCOMING_DIR = "incoming_pdfs"

os.makedirs(INCOMING_DIR, exist_ok=True)

# Enhanced logging function
def log_message(level, message, error=None):
    """
    Enhanced logging with timestamp and error details
    level: INFO, WARNING, ERROR, SUCCESS
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{timestamp}] [{level}] [Financial Analyzer]"
    
    print(f"{prefix} {message}")
    
    if error:
        print(f"{prefix} Error Details: {str(error)}")
        print(f"{prefix} Error Type: {type(error).__name__}")
        if hasattr(error, '__traceback__'):
            print(f"{prefix} Traceback:")
            traceback.print_exception(type(error), error, error.__traceback__)

# Document type detection helper
def detect_document_type(text):
    """Auto-detect financial document type from content"""
    try:
        text_lower = text.lower()
        if "bank statement" in text_lower or "account balance" in text_lower or "checking account" in text_lower:
            detected = "bank_statement"
        elif "credit report" in text_lower or "credit score" in text_lower or "fico" in text_lower or "experian" in text_lower:
            detected = "credit_report"
        else:
            detected = "generic"
        
        log_message("INFO", f"Document type detected: {detected}")
        return detected
    except Exception as e:
        log_message("ERROR", "Error detecting document type, defaulting to 'generic'", e)
        return "generic"

def test_email_connection():
    """Test email credentials before starting the worker"""
    log_message("INFO", "Testing email connection...")
    
    if not EMAIL or not PASSWORD:
        log_message("ERROR", "EMAIL_ADDRESS or EMAIL_PASSWORD not set in environment variables!")
        return False
    
    log_message("INFO", f"Using email: {EMAIL}")
    log_message("INFO", f"Password length: {len(PASSWORD)} characters")
    
    try:
        # Test IMAP connection
        log_message("INFO", "Testing IMAP connection to imap.gmail.com:993...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")
        log_message("SUCCESS", "✓ IMAP connection successful!")
        mail.logout()
        
        # Test SMTP connection
        log_message("INFO", "Testing SMTP connection to smtp.gmail.com:465...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL, PASSWORD)
        log_message("SUCCESS", "✓ SMTP connection successful!")
        
        return True
        
    except imaplib.IMAP4.error as e:
        log_message("ERROR", "IMAP authentication failed! Check your EMAIL_ADDRESS and EMAIL_PASSWORD (use App Password, not regular password)", e)
        return False
    except smtplib.SMTPAuthenticationError as e:
        log_message("ERROR", "SMTP authentication failed! Check your App Password", e)
        return False
    except Exception as e:
        log_message("ERROR", "Connection test failed", e)
        return False

def check_inbox_periodically():
    log_message("INFO", "Email worker starting up...")
    
    # Test connection first
    if not test_email_connection():
        log_message("ERROR", "Email connection test failed! Worker will not start.")
        log_message("ERROR", "Please check: 1) 2FA is enabled on Gmail, 2) App Password is generated, 3) Environment variables are set correctly")
        return
    
    log_message("SUCCESS", "Email worker initialized successfully. Starting periodic checks...")
    
    check_count = 0
    
    while True:
        check_count += 1
        log_message("INFO", f"===== Check #{check_count} - Starting inbox scan =====")
        
        try:
            log_message("INFO", "Connecting to Gmail IMAP...")
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(EMAIL, PASSWORD)
            mail.select("inbox")
            log_message("SUCCESS", "Connected to inbox")

            # Calculate date for 24 hours ago
            date_24_hours_ago = (date.today() - timedelta(days=1)).strftime("%d-%b-%Y")
            log_message("INFO", f"Searching for unseen emails since: {date_24_hours_ago}")
            
            # Search for unseen emails from the last 24 hours
            status, email_ids = mail.search(None, 
                                            f'(UNSEEN SENTSINCE "{date_24_hours_ago}")')
            
            email_list = email_ids[0].split()
            log_message("INFO", f"Found {len(email_list)} unseen email(s)")
            
            if len(email_list) == 0:
                log_message("INFO", "No new emails to process")
            
            for idx, email_id in enumerate(email_list, 1):
                log_message("INFO", f"Processing email {idx}/{len(email_list)} (ID: {email_id.decode()})")
                
                try:
                    status, msg_data = mail.fetch(email_id, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])

                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8")

                    sender, encoding = decode_header(msg["From"])[0]
                    if isinstance(sender, bytes):
                        sender = sender.decode(encoding or "utf-8")

                    log_message("INFO", f"Email from: {sender}")
                    log_message("INFO", f"Subject: {subject}")

                    has_pdf_attachment = False
                    attachment_count = 0
                    
                    for part in msg.walk():
                        try:
                            content_type = part.get_content_type()
                            log_message("INFO", f"Checking email part: {content_type}")
                            
                            if part.get_content_maintype() == "application" and part.get_content_subtype() == "pdf":
                                has_pdf_attachment = True
                                attachment_count += 1
                                filename = part.get_filename()
                                
                                if filename:
                                    filepath = os.path.join(INCOMING_DIR, filename)
                                    log_message("SUCCESS", f"✓ Found PDF attachment: {filename}")
                                    log_message("INFO", f"Saving to: {filepath}")
                                    
                                    with open(filepath, "wb") as f:
                                        payload = part.get_payload(decode=True)
                                        f.write(payload)
                                    
                                    file_size = os.path.getsize(filepath)
                                    log_message("SUCCESS", f"✓ PDF saved successfully ({file_size} bytes)")

                                    # Process PDF, analyze document, and send email
                                    process_and_respond(filepath, sender, subject)
                                else:
                                    log_message("WARNING", "PDF attachment found but no filename available")
                            elif part.get_content_maintype() == "multipart":
                                log_message("INFO", "Multipart section, continuing to walk...")
                            else:
                                log_message("INFO", f"Skipping non-PDF part: {content_type}")
                                
                        except AttributeError as ae:
                            log_message("ERROR", f"AttributeError processing email part", ae)
                        except Exception as part_e:
                            log_message("ERROR", f"Unexpected error processing email part", part_e)
                    
                    if not has_pdf_attachment:
                        log_message("WARNING", f"No PDF attachments found in email from {sender}")
                    else:
                        log_message("SUCCESS", f"✓ Processed {attachment_count} PDF attachment(s)")

                    # Mark as seen
                    mail.store(email_id, "+FLAGS", "\\Seen")
                    log_message("INFO", "Email marked as seen")
                    
                except Exception as email_error:
                    log_message("ERROR", f"Error processing individual email (ID: {email_id.decode()})", email_error)

            mail.logout()
            log_message("SUCCESS", f"✓ Check #{check_count} completed. Disconnected from inbox.")

        except imaplib.IMAP4.error as imap_error:
            log_message("ERROR", "IMAP error occurred", imap_error)
        except Exception as e:
            log_message("ERROR", "Unexpected error in email worker main loop", e)
        
        log_message("INFO", f"Waiting 5 minutes before next check... (Next check at {(datetime.now() + timedelta(seconds=300)).strftime('%H:%M:%S')})")
        time.sleep(10)  # Check every 300 seconds (5 minutes)

def process_and_respond(pdf_path, recipient_email, original_subject):
    log_message("INFO", f"===== Starting PDF Processing =====")
    log_message("INFO", f"PDF: {pdf_path}")
    log_message("INFO", f"Recipient: {recipient_email}")
    
    try:
        # Extract text from PDF
        log_message("INFO", "Step 1: Extracting text from PDF...")
        extracted_text = process_single_pdf(pdf_path)
        text_length = len(extracted_text)
        log_message("SUCCESS", f"✓ Text extracted successfully ({text_length} characters)")
        
        if text_length < 50:
            log_message("WARNING", f"Extracted text is very short ({text_length} chars). PDF might be image-based or corrupted.")
        
        # Detect document type
        log_message("INFO", "Step 2: Detecting document type...")
        doc_type = detect_document_type(extracted_text)
        log_message("SUCCESS", f"✓ Document type: {doc_type}")
        
        # Analyze document
        log_message("INFO", "Step 3: Analyzing document with AI...")
        analysis_result = analyze_document(extracted_text, doc_type)
        
        # Check for errors
        if isinstance(analysis_result, dict) and "error" in analysis_result:
            log_message("ERROR", f"AI analysis returned error: {analysis_result['error']}")
            error_msg_to_send = str(analysis_result["error"])
            send_email_error(recipient_email, original_subject, error_msg_to_send)
            return

        log_message("SUCCESS", "✓ AI analysis completed successfully")
        log_message("INFO", f"Analysis summary: {json.dumps(analysis_result, indent=2)[:500]}...")  # First 500 chars

        # Transform result
        log_message("INFO", "Step 4: Formatting results...")
        frontend_result = {
            "name": analysis_result.get("client_name", "Unknown"),
            "email": recipient_email,
            "course": doc_type.replace("_", " ").title(),
            "grade_output": f"Assessment: {analysis_result.get('overall_assessment', 'Pending Review')}\n\nSummary: {analysis_result.get('analysis_summary', 'No summary available')}\n\nKey Findings: {analysis_result.get('key_findings', 'No findings')}\n\nRed Flags: {analysis_result.get('red_flags', 'None identified')}\n\nRecommendations: {analysis_result.get('recommendations', 'No recommendations')}",
            "timestamp": datetime.now().isoformat(),
            "criteria_scores": analysis_result.get("criteria_analysis", []),
            "document_type": doc_type,
            "red_flags": analysis_result.get("red_flags", "None identified")
        }

        # Save result
        log_message("INFO", "Step 5: Saving results to file...")
        write_result_to_file(frontend_result)
        log_message("SUCCESS", "✓ Results saved to file")

        # Format email
        log_message("INFO", "Step 6: Formatting email feedback...")
        feedback_for_email = f"FINANCIAL DOCUMENT ANALYSIS REPORT\n\n"
        feedback_for_email += f"Document Type: {doc_type.replace('_', ' ').upper()}\n"
        feedback_for_email += f"Overall Assessment: {analysis_result.get('overall_assessment', 'N/A')}\n\n"
        feedback_for_email += f"SUMMARY:\n{analysis_result.get('analysis_summary', 'N/A')}\n\n"
        feedback_for_email += f"KEY FINDINGS:\n{analysis_result.get('key_findings', 'N/A')}\n\n"
        
        feedback_for_email += "DETAILED ANALYSIS:\n"
        for criterion in analysis_result.get("criteria_analysis", []):
            findings = criterion.get("findings", "N/A").replace("{", "{{").replace("}", "}}")
            assessment = criterion.get("assessment", "N/A")
            notes = criterion.get("notes", "").replace("{", "{{").replace("}", "}}")

            feedback_for_email += f"\n{criterion.get('criterion', 'N/A')}:\n"
            feedback_for_email += f"  Findings: {findings}\n"
            feedback_for_email += f"  Assessment: {assessment}\n"
            if notes:
                feedback_for_email += f"  Notes: {notes}\n"
        
        red_flags = analysis_result.get("red_flags", "None identified")
        if red_flags and red_flags != "None identified":
            feedback_for_email += f"\n⚠️ RED FLAGS:\n{red_flags}\n"
        
        feedback_for_email += f"\nRECOMMENDATIONS:\n{analysis_result.get('recommendations', 'N/A')}\n"
        feedback_for_email += "\n---\nThis is an automated analysis. Please review the original document for complete details."

        # Send email
        log_message("INFO", "Step 7: Sending email feedback...")
        send_email_feedback(recipient_email, original_subject, feedback_for_email)
        
        log_message("SUCCESS", f"✓✓✓ All steps completed successfully for {recipient_email} ✓✓✓")

    except Exception as e:
        log_message("ERROR", f"Critical error in process_and_respond for {pdf_path}", e)
        error_msg_to_send = str(e)
        send_email_error(recipient_email, original_subject, error_msg_to_send)

def send_email_feedback(recipient_email, original_subject, feedback):
    log_message("INFO", f"Preparing to send feedback email to: {recipient_email}")
    
    try:
        msg = MIMEText(feedback)
        msg["Subject"] = f"Re: {original_subject} - Financial Document Analysis Report"
        msg["From"] = EMAIL
        msg["To"] = recipient_email

        log_message("INFO", "Connecting to SMTP server (smtp.gmail.com:465)...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            log_message("INFO", "Authenticating with SMTP...")
            smtp.login(EMAIL, PASSWORD)
            log_message("INFO", "Sending email message...")
            smtp.send_message(msg)
        
        log_message("SUCCESS", f"✓ Feedback email sent successfully to {recipient_email}")
        
    except smtplib.SMTPAuthenticationError as auth_error:
        log_message("ERROR", f"SMTP Authentication failed when sending to {recipient_email}. Check App Password!", auth_error)
    except smtplib.SMTPException as smtp_error:
        log_message("ERROR", f"SMTP error when sending to {recipient_email}", smtp_error)
    except OSError as os_error:
        log_message("ERROR", f"Network error when sending to {recipient_email}. Check if SMTP ports are blocked on Render!", os_error)
    except Exception as e:
        log_message("ERROR", f"Unexpected error sending feedback email to {recipient_email}", e)

def send_email_error(recipient_email, original_subject, error_message):
    log_message("INFO", f"Preparing to send ERROR notification email to: {recipient_email}")
    
    try:
        escaped_error_message = error_message.replace("{", "{{").replace("}", "}}")
        error_body = f"An error occurred while processing your financial document (Subject: {original_subject}):\n\n{escaped_error_message}\n\nPlease ensure the document is a valid PDF and try again, or contact our support team."
        
        msg = MIMEText(error_body)
        msg["Subject"] = f"Re: {original_subject} - Error Processing Document"
        msg["From"] = EMAIL
        msg["To"] = recipient_email

        log_message("INFO", "Connecting to SMTP server for error notification...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL, PASSWORD)
            smtp.send_message(msg)
        
        log_message("SUCCESS", f"✓ Error notification sent to {recipient_email}")
        
    except Exception as e:
        log_message("ERROR", f"Failed to send error notification to {recipient_email}", e)

if __name__ == "__main__":
    log_message("INFO", "========================================")
    log_message("INFO", "  Financial Analyzer Email Worker")
    log_message("INFO", "========================================")
    check_inbox_periodically()
