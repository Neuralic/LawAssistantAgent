import os
import google.generativeai as genai
from dotenv import load_dotenv
import json

load_dotenv()

INCOMING_DIR = "incoming_pdfs"

# Ensure the directory exists (create if not)
if not os.path.exists(INCOMING_DIR):
    os.makedirs(INCOMING_DIR)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Add a print statement to check if the API key is loaded
if GEMINI_API_KEY:
    print("GEMINI_API_KEY loaded successfully.")
else:
    print("GEMINI_API_KEY not found. Please ensure it\"s set in your environment variables.")

genai.configure(api_key=GEMINI_API_KEY)

# Updated model name based on available models from Render logs
model = genai.GenerativeModel("gemini-2.5-flash")

def load_rubric(rubric_name):
    try:
        with open("rubrics.json", "r") as f:
            rubrics = json.load(f)
        return rubrics.get(rubric_name)
    except FileNotFoundError:
        print("Error: rubrics.json not found.")
        return None
    except json.JSONDecodeError:
        print("Error: Could not decode rubrics.json. Check JSON format.")
        return None

def format_rubric_for_prompt(rubric_data):
    if not rubric_data:
        return "No rubric provided."
    
    formatted_rubric = f"Rubric Name: {rubric_data.get("name", "N/A")}\n"
    formatted_rubric += f"Description: {rubric_data.get("description", "N/A")}\n\n"
    
    for criterion in rubric_data.get("criteria", []):
        formatted_rubric += f"Criteria: {criterion.get("title", "N/A")} ({criterion.get("points", 0)} points)\n"
        formatted_rubric += f"Description: {criterion.get("description", "N/A")}\n"
        formatted_rubric += "\n"
    return formatted_rubric

def analyze_document(document_text, rubric_name="generic"):
    rubric_data = load_rubric(rubric_name)
    formatted_rubric = format_rubric_for_prompt(rubric_data)

    if not rubric_data:
        return {"error": f"Rubric {rubric_name} not found or could not be loaded."}

    # Define the JSON structure as a Python dictionary
    json_structure = {
        "client_name": "[Client/Account holder name, extracted from document if possible, otherwise 'Unknown']",
        "document_type": "[Type of document: Bank Statement, Credit Report, or Other Financial Document]",
        "analysis_summary": "[Brief summary of document analysis and key findings]",
        "overall_assessment": "[Overall risk assessment: Low Risk, Moderate Risk, High Risk, or Requires Review]",
        "key_findings": "[List of critical findings, extracted data, and important numbers]",
        "criteria_analysis": [
            {
                "criterion": "[Criterion Name]",
                "findings": "[Specific findings for this criterion with actual data and numbers]",
                "assessment": "[Assessment: Complete, Incomplete, or Concerning]",
                "notes": "[Additional notes or recommendations]"
            }
        ],
        "red_flags": "[Any concerning items, inconsistencies, or items requiring legal review]",
        "recommendations": "[Recommended next steps or actions for the legal team]"
    }

    # Convert the dictionary to a JSON string, handling all escaping automatically
    json_format_instruction = json.dumps(json_structure, indent=4)

    prompt = f"""You are an AI assistant acting as a Senior Financial Analyst and Legal Document Reviewer working for a law firm. Your task is to analyze financial documents (bank statements, credit reports, etc.) based on the provided analysis criteria.
    
    Here are the analysis criteria for this document:
    {formatted_rubric}

    Here is the financial document to analyze:
    {document_text}

    Please provide a detailed analysis based on the criteria above. Extract ALL relevant financial data including:
    - Account/personal information
    - Specific dollar amounts, balances, and transactions
    - Dates and time periods
    - Payment histories and patterns
    - Any red flags or concerning items
    - Credit scores, limits, and utilization (for credit reports)
    - Income and expense patterns (for bank statements)
    
    Your response MUST be a valid JSON object ONLY. Do NOT include any other text, explanations, or formatting outside the JSON object. 
    Be thorough and extract actual numbers and data from the document.
    The JSON object should strictly follow this format:
{json_format_instruction}
    """

    try:
        response = model.generate_content(prompt)
        print(f"[Financial Analyzer] Processing document...")
        print(f"[Financial Analyzer] Response type: {type(response)}")

        raw_response_text = ""
        if hasattr(response, 'text'):
            raw_response_text = response.text
        elif isinstance(response, str):
            raw_response_text = response
        else:
            raw_response_text = str(response)

        # Attempt to extract JSON from the raw response text
        json_start = raw_response_text.find('{')
        json_end = raw_response_text.rfind('}')

        if json_start != -1 and json_end != -1 and json_end > json_start:
            json_string = raw_response_text[json_start : json_end + 1]
            try:
                json_response = json.loads(json_string)
                print(f"Successfully parsed JSON: {json_response}")
                return json_response
            except json.JSONDecodeError as e:
                print(f"Error decoding extracted JSON: {e}")
                print(f"Extracted JSON string: {json_string}")
                return {"error": f"Failed to parse AI response as JSON: {e}", "raw_response": raw_response_text}
        else:
            print(f"No valid JSON object found in AI response: {raw_response_text}")
            return {"error": "No valid JSON object found in AI response", "raw_response": raw_response_text}

    except Exception as e:
        print(f"Error during grading: {e}")
        return {"error": f"Error during grading: {e}"}

# Maintain backward compatibility
def grade_assignment(assignment_text, rubric_name="generic"):
    """Backward compatible wrapper for analyze_document"""
    return analyze_document(assignment_text, rubric_name)

if __name__ == "__main__":
    # Example usage:
    sample_bank_statement = """Bank Statement - ABC Bank
    Account Holder: John Doe
    Account Number: ****5678
    Statement Period: January 1-31, 2024
    Opening Balance: $5,234.56
    Closing Balance: $3,890.23
    
    Deposits:
    01/05 - Direct Deposit - ACME Corp - $3,200.00
    01/15 - Mobile Deposit - $150.00
    
    Withdrawals:
    01/03 - Rent Payment - $1,850.00
    01/10 - Grocery Store - $234.50
    01/28 - ATM Withdrawal - $500.00
    """
    analysis = analyze_document(sample_bank_statement, "bank_statement")
    print(analysis)