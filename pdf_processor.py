import os
import re
from PyPDF2 import PdfReader

INCOMING_DIR = "incoming_pdfs"

def extract_text_from_pdf(file_path):
    print(f"[PDF Processor] Attempting to extract text from PDF: {file_path}")
    try:
        reader = PdfReader(file_path)
        text = ""
        num_pages = len(reader.pages)
        print(f"[PDF Processor] Document has {num_pages} pages")
        
        for i, page in enumerate(reader.pages, 1):
            page_text = page.extract_text() or ""
            text += page_text
            print(f"[PDF Processor] Extracted {len(page_text)} characters from page {i}")
        
        print(f"[PDF Processor] Successfully extracted text from {file_path}. Total length: {len(text)} characters")
        return text
    except Exception as e:
        print(f"[PDF Processor] Error reading PDF {file_path}: {e}")
        return ""

def extract_client_data(text):
    """Extract client/account holder information from financial documents"""
    # Try multiple patterns for name extraction
    name_patterns = [
        r"(?:Account Holder|Name|Client|Customer):\s*(.+)",
        r"(?:Primary Account Holder):\s*(.+)",
        r"(?:Account Name):\s*(.+)"
    ]
    
    client_name = "Unknown Client"
    for pattern in name_patterns:
        name_match = re.search(pattern, text, re.IGNORECASE)
        if name_match:
            client_name = name_match.group(1).strip()
            # Remove any trailing numbers or account info
            client_name = re.sub(r'\s+\d{4,}.*$', '', client_name)
            break
    
    # Extract account number if present
    account_match = re.search(r"(?:Account|Acct)\s*(?:Number|#)?\s*[:\-]?\s*([\*\d]{4,})", text, re.IGNORECASE)
    account_number = account_match.group(1).strip() if account_match else "Not Found"
    
    # Extract document date
    date_patterns = [
        r"(?:Statement Date|Report Date|As of):\s*([\d/\-]+)",
        r"(?:Date):\s*([\d/\-]+)",
    ]
    
    document_date = "Unknown Date"
    for pattern in date_patterns:
        date_match = re.search(pattern, text, re.IGNORECASE)
        if date_match:
            document_date = date_match.group(1).strip()
            break
    
    print(f"[PDF Processor] Extracted client data: Name={client_name}, Account={account_number}, Date={document_date}")
    return client_name, account_number, document_date

# Backward compatibility
def extract_student_data(text):
    """Backward compatible wrapper for extract_client_data"""
    client_name, account_number, document_date = extract_client_data(text)
    return client_name, "Financial Document", document_date

def process_single_pdf(file_path):
    print(f"[PDF Processor] Processing single PDF: {file_path}")
    # Ensure the directory exists (create if not)
    if not os.path.exists(INCOMING_DIR):
        os.makedirs(INCOMING_DIR)
        print(f"[PDF Processor] Created directory: {INCOMING_DIR}")

    # Extract text from the uploaded file
    text = extract_text_from_pdf(file_path)
    
    # Extract and log client information
    if text:
        extract_client_data(text)
    
    return text


if __name__ == '__main__':
    # Example Usage:
    # Create a dummy PDF file for testing
    # with open("dummy.pdf", "w") as f:
    #     f.write("This is a dummy PDF content.")

    # extracted_text = process_single_pdf("dummy.pdf")
    # print(f"Extracted Text: {extracted_text}")

    # student_name, course_name, assignment_name = extract_student_data(extracted_text)
    # print(f"Student Name: {student_name}")
    # print(f"Course Name: {course_name}")
    # print(f"Assignment Name: {assignment_name}")
    pass

