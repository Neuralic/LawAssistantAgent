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

load_dotenv()

EMAIL = os.getenv("EMAIL_ADDRESS")
PASSWORD = os.getenv("EMAIL_PASSWORD")
INCOMING_DIR = "incoming_pdfs"

os.makedirs(INCOMING_DIR, exist_ok=True)

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
            mail.login(EMAIL, PASSWORD)
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
        time.sleep(15)  # Check every 300 seconds (5 minutes)

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
            findings = criterion.get("findings", "N/A").replace("{", "{{").replace("}", "}}")
            assessment = criterion.get("assessment", "N/A")
            notes = criterion.get("notes", "").replace("{", "{{").replace("}", "}}")

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

        send_email_feedback(recipient_email, original_subject, feedback_for_email)
        print(f"[Financial Analyzer] Analysis report sent to {recipient_email}")

    except Exception as e:
        print(f"Error processing and responding to PDF {pdf_path}: {e}")
        # Ensure the error message is a plain string before passing
        error_msg_to_send = str(e)
        send_email_error(recipient_email, original_subject, error_msg_to_send)

def send_email_feedback(recipient_email, original_subject, feedback):
    try:
        msg = MIMEText(feedback)
        msg["Subject"] = f"Re: {original_subject} - Financial Document Analysis Report"
        msg["From"] = EMAIL
        msg["To"] = recipient_email

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL, PASSWORD)
            smtp.send_message(msg)
        print(f"[Financial Analyzer] Analysis report email sent to {recipient_email}")
    except Exception as e:
        print(f"[Financial Analyzer] Error sending analysis report to {recipient_email}: {e}")

def send_email_error(recipient_email, original_subject, error_message):
    try:
        # Escape curly braces in the error_message itself
        escaped_error_message = error_message.replace("{", "{{").replace("}", "}}")
        error_body = f"An error occurred while processing your financial document (Subject: {original_subject}):\n\n{escaped_error_message}\n\nPlease ensure the document is a valid PDF and try again, or contact our support team."
        msg = MIMEText(error_body)
        msg["Subject"] = f"Re: {original_subject} - Error Processing Document"
        msg["From"] = EMAIL
        msg["To"] = recipient_email

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL, PASSWORD)
            smtp.send_message(msg)
        print(f"[Financial Analyzer] Error email sent to {recipient_email}")
    except Exception as e:
        print(f"[Financial Analyzer] Error sending error email to {recipient_email}: {e}")

if __name__ == "__main__":
    print("[Financial Analyzer] Email worker started. Monitoring inbox for financial documents...")
    # check_inbox_periodically() # Uncomment to run directly for testing
