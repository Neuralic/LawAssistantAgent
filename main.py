from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from email_worker import check_inbox_periodically
from grader_utils import read_all_results, write_result_to_file
from pdf_processor import process_single_pdf
from grader import analyze_document
import threading
import os
import shutil
import json
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def serve_home():
    """Serve the main index.html file"""
    return FileResponse("index.html")

@app.get("/style.css")
async def serve_css():
    """Serve the CSS file"""
    return FileResponse("style.css")

@app.post("/upload-pdf/")
async def upload_pdf(file: UploadFile = File(...), document_type: str = "auto"):
    file_path = f"./{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Process the PDF and extract text
    text = process_single_pdf(file_path)
    
    # Auto-detect document type if not specified
    if document_type == "auto":
        text_lower = text.lower()
        if "bank statement" in text_lower or "account balance" in text_lower or "transaction" in text_lower:
            document_type = "bank_statement"
        elif "credit report" in text_lower or "credit score" in text_lower or "fico" in text_lower:
            document_type = "credit_report"
        else:
            document_type = "generic"
    
    # Analyze the document using appropriate rubric
    analysis_result = analyze_document(text, document_type)
    
    # Transform the response to match frontend expectations
    result = {
        "filename": file.filename,
        "client_name": analysis_result.get("client_name", "Unknown"),
        "document_type": analysis_result.get("document_type", document_type),
        "overall_assessment": analysis_result.get("overall_assessment", "Pending Review"),
        "analysis_summary": analysis_result.get("analysis_summary", "No analysis available"),
        "key_findings": analysis_result.get("key_findings", "No findings"),
        "red_flags": analysis_result.get("red_flags", "None identified"),
        "recommendations": analysis_result.get("recommendations", "No recommendations"),
        "criteria_analysis": analysis_result.get("criteria_analysis", [])
    }
    
    # Save to results file with frontend-compatible format
    frontend_result = {
        "name": result["client_name"],
        "email": "",  # Not available from PDF upload
        "course": result["document_type"].replace("_", " ").title(),
        "grade_output": f"Assessment: {result['overall_assessment']}\n\nSummary: {result['analysis_summary']}\n\nKey Findings: {result['key_findings']}\n\nRed Flags: {result['red_flags']}\n\nRecommendations: {result['recommendations']}",
        "timestamp": datetime.now().isoformat(),
        "criteria_scores": result["criteria_analysis"],
        "document_type": result["document_type"],
        "red_flags": result["red_flags"]
    }
    
    write_result_to_file(frontend_result)
    
    return result

@app.get("/results/")
async def get_results():
    results = read_all_results()
    return results

@app.post("/analyze-all/")
async def analyze_all():
    """Endpoint to process all pending document submissions"""
    # This would typically process files in a queue
    # For now, return a success message
    return {"message": "All documents processed", "processed_count": 0}

# Backward compatibility endpoint
@app.post("/grade-all/")
async def grade_all():
    return await analyze_all()

# Start the email worker in a separate thread
@app.on_event("startup")
async def startup_event():
    thread = threading.Thread(target=check_inbox_periodically)
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
