import imaplib
import email
import os
import time
import resend
from email.header import decode_header
from dotenv import load_dotenv
from pdf_processor import process_single_pdf
from grader import analyze_document
from grader_utils import write_result_to_file
from datetime import datetime, date, timedelta
import json
import traceback

load_dotenv()

# Gmail credentials for RECEIVING emails via IMAP
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")  # Your actual Gmail for receiving PDFs
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")  # Gmail app password

# Resend credentials for SENDING emails
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")  # Default to free tier
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

INCOMING_DIR = "incoming_pdfs"

os.makedirs(INCOMING_DIR, exist_ok=True)

# Configure Resend with detailed logging
print(f"[DEBUG] GMAIL_ADDRESS (for receiving): {GMAIL_ADDRESS}")
print(f"[DEBUG] RESEND_FROM_EMAIL (for sending): {RESEND_FROM_EMAIL}")
print(f"[DEBUG] RESEND_API_KEY present: {bool(RESEND_API_KEY)}")
if RESEND_API_KEY:
    print(f"[DEBUG] RESEND_API_KEY length: {len(RESEND_API_KEY)}")
    print(f"[DEBUG] RESEND_API_KEY starts with: {RESEND_API_KEY[:7] if len(RESEND_API_KEY) > 7 else 'TOO_SHORT'}")
    resend.api_key = RESEND_API_KEY
    print("[Financial Analyzer] Resend API configured successfully.")
else:
    print("[Financial Analyzer] WARNING: RESEND_API_KEY not found. Email sending will fail.")

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
            
            print(f"Found {len(email_ids[0].split())} unseen emails from the last 24 hours.")
            for email_id in email_ids[0].split():
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])

                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding or "utf-8")

                sender, encoding = decode_header(msg["From"])[0]
                if isinstance(sender, bytes):
                    sender = sender.decode(encoding or "utf-8")

                print(f"[Financial Analyzer] Processing email from: {sender} with subject: {subject}")

                has_pdf_attachment = False
                for part in msg.walk():
                    try:
                        print(f"Checking part: {part.get_content_type()}")
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
                                process_and_respond(filepath, sender, subject)
                            else:
                                print("PDF attachment found but no filename.")
                        elif part.get_content_maintype() == "multipart":
                            print("Multipart email part, continuing to walk.")
                        else:
                            print(f"Skipping non-PDF part: {part.get_content_type()}")
                    except AttributeError as ae:
                        print(f"AttributeError when processing email part: {ae}. Part type: {type(part)}. Part content: {part}")
                        print("This part might not be a valid email.message.Message object.")
                    except Exception as part_e:
                        print(f"Unexpected error when processing email part: {part_e}. Part type: {type(part)}")
                
                if not has_pdf_attachment:
                    print(f"No PDF attachment found in email from {sender} with subject: {subject}")

                mail.store(email_id, "+FLAGS", "\\Seen")

            mail.logout()

        except Exception as e:
            print(f"Error in email worker: {e}")
            traceback.print_exc()
        time.sleep(10)  # Check every 10 seconds

def process_and_respond(pdf_path, recipient_email, original_subject):
    try:
        print(f"[Financial Analyzer] Attempting to process PDF: {pdf_path}")
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

        print(f"[Financial Analyzer] Generated analysis: {json.dumps(analysis_result, indent=2)}")

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

        # Format feedback for email
        feedback_for_email = f"FINANCIAL DOCUMENT ANALYSIS REPORT\n\n"
        feedback_for_email += f"Document Type: {doc_type.replace('_', ' ').upper()}\n"
        feedback_for_email += f"Overall Assessment: {analysis_result.get('overall_assessment', 'N/A')}\n\n"
        feedback_for_email += f"SUMMARY:\n{analysis_result.get('analysis_summary', 'N/A')}\n\n"
        feedback_for_email += f"KEY FINDINGS:\n{analysis_result.get('key_findings', 'N/A')}\n\n"
        
        # Add criteria analysis
        feedback_for_email += "DETAILED ANALYSIS:\n"
        for criterion in analysis_result.get("criteria_analysis", []):
            findings = criterion.get("findings", "N/A")
            assessment = criterion.get("assessment", "N/A")
            notes = criterion.get("notes", "")

            feedback_for_email += f"\n{criterion.get('criterion', 'N/A')}:\n"
            feedback_for_email += f"  Findings: {findings}\n"
            feedback_for_email += f"  Assessment: {assessment}\n"
            if notes:
                feedback_for_email += f"  Notes: {notes}\n"
        
        # Add red flags section
        red_flags = analysis_result.get("red_flags", "None identified")
        if red_flags and red_flags != "None identified":
            feedback_for_email += f"\n⚠️ RED FLAGS:\n{red_flags}\n"
        
        feedback_for_email += f"\nRECOMMENDATIONS:\n{analysis_result.get('recommendations', 'N/A')}\n"
        feedback_for_email += "\n---\nThis is an automated analysis. Please review the original document for complete details."

        print(f"[DEBUG] About to call send_email_feedback")
        print(f"[DEBUG] Recipient: {recipient_email}")
        print(f"[DEBUG] Subject: {original_subject}")
        print(f"[DEBUG] Feedback length: {len(feedback_for_email)} characters")
        
        send_email_feedback(recipient_email, original_subject, feedback_for_email)
        print(f"[Financial Analyzer] Analysis report sent to {recipient_email}")

    except Exception as e:
        print(f"[ERROR] Error processing and responding to PDF {pdf_path}: {e}")
        print(f"[ERROR] Full traceback:")
        traceback.print_exc()
        error_msg_to_send = str(e)
        send_email_error(recipient_email, original_subject, error_msg_to_send)

def send_email_feedback(recipient_email, original_subject, feedback):
    """Send analysis feedback email with comprehensive error logging"""
    print(f"\n{'='*60}")
    print(f"[EMAIL SEND] Starting send_email_feedback function")
    print(f"{'='*60}")
    
    try:
        # Extract email address from "Name <email@domain.com>" format
        import re
        print(f"[EMAIL SEND] Raw recipient_email: {recipient_email}")
        
        email_match = re.search(r'<(.+?)>', recipient_email)
        clean_email = email_match.group(1) if email_match else recipient_email
        
        print(f"[EMAIL SEND] Cleaned recipient email: {clean_email}")
        print(f"[EMAIL SEND] From address (RESEND_FROM_EMAIL): {RESEND_FROM_EMAIL}")
        print(f"[EMAIL SEND] Subject: Re: {original_subject} - Financial Document Analysis Report")
        print(f"[EMAIL SEND] Feedback preview (first 200 chars): {feedback[:200]}")
        
        # Verify Resend API key is still set
        print(f"[EMAIL SEND] Resend API key configured: {bool(resend.api_key)}")
        
        # Build email params
        params = {
            "from": f"Financial Analyzer <{RESEND_FROM_EMAIL}>",
            "to": [clean_email],
            "subject": f"Re: {original_subject} - Financial Document Analysis Report",
            "text": feedback
        }
        
        print(f"[EMAIL SEND] Email params prepared:")
        print(f"  - from: {params['from']}")
        print(f"  - to: {params['to']}")
        print(f"  - subject length: {len(params['subject'])}")
        print(f"  - text length: {len(params['text'])}")
        
        print(f"[EMAIL SEND] Calling resend.Emails.send()...")
        response = resend.Emails.send(params)
        
        print(f"[EMAIL SEND] ✅ SUCCESS! Response received:")
        print(f"[EMAIL SEND] Response type: {type(response)}")
        print(f"[EMAIL SEND] Response content: {response}")
        
        if isinstance(response, dict):
            email_id = response.get('id', 'NO_ID')
            print(f"[EMAIL SEND] Email ID: {email_id}")
        
        print(f"[Financial Analyzer] Analysis report email sent to {clean_email} via Resend")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"\n{'='*60}")
        print(f"[EMAIL SEND] ❌ ERROR occurred!")
        print(f"{'='*60}")
        print(f"[EMAIL SEND] Error type: {type(e).__name__}")
        print(f"[EMAIL SEND] Error message: {str(e)}")
        print(f"[EMAIL SEND] Full traceback:")
        traceback.print_exc()
        print(f"{'='*60}\n")
        
        # Re-raise to let calling function know it failed
        raise

def send_email_error(recipient_email, original_subject, error_message):
    """Send error notification email with comprehensive error logging"""
    print(f"\n{'='*60}")
    print(f"[ERROR EMAIL] Starting send_email_error function")
    print(f"{'='*60}")
    
    try:
        # Extract email address from "Name <email@domain.com>" format
        import re
        print(f"[ERROR EMAIL] Raw recipient_email: {recipient_email}")
        
        email_match = re.search(r'<(.+?)>', recipient_email)
        clean_email = email_match.group(1) if email_match else recipient_email
        
        print(f"[ERROR EMAIL] Cleaned recipient email: {clean_email}")
        print(f"[ERROR EMAIL] From address: {RESEND_FROM_EMAIL}")
        
        error_body = f"An error occurred while processing your financial document (Subject: {original_subject}):\n\n{error_message}\n\nPlease ensure the document is a valid PDF and try again, or contact our support team."
        
        print(f"[ERROR EMAIL] Error message length: {len(error_body)}")
        
        # Send via Resend API
        params = {
            "from": f"Financial Analyzer <{RESEND_FROM_EMAIL}>",
            "to": [clean_email],
            "subject": f"Re: {original_subject} - Error Processing Document",
            "text": error_body
        }
        
        print(f"[ERROR EMAIL] Calling resend.Emails.send()...")
        response = resend.Emails.send(params)
        
        print(f"[ERROR EMAIL] ✅ SUCCESS! Response: {response}")
        print(f"[Financial Analyzer] Error email sent to {clean_email} via Resend")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"\n{'='*60}")
        print(f"[ERROR EMAIL] ❌ Failed to send error email!")
        print(f"{'='*60}")
        print(f"[ERROR EMAIL] Error type: {type(e).__name__}")
        print(f"[ERROR EMAIL] Error message: {str(e)}")
        print(f"[ERROR EMAIL] Full traceback:")
        traceback.print_exc()
        print(f"{'='*60}\n")

if __name__ == "__main__":
    print("[Financial Analyzer] Email worker started. Monitoring inbox for financial documents...")
    print(f"[DEBUG] Monitoring Gmail: {GMAIL_ADDRESS}")
    print(f"[DEBUG] Sending from (Resend): {RESEND_FROM_EMAIL}")
    print(f"[DEBUG] Resend configured: {bool(RESEND_API_KEY)}")
    # check_inbox_periodically() # Uncomment to run directly for testing
