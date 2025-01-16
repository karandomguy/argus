from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from modules.report_generator import ReportGenerator, save_report
from modules.search import search_and_extract
from modules.org_data import PartyDataFetcher  # Make sure org_data.py defines PartyDataFetcher

app = FastAPI()

# Models for input validation
class ReportRequest(BaseModel):
    topic: str
    max_results: Optional[int] = 3

class PartyRequest(BaseModel):
    party_name: str

# Initialize classes
report_generator = ReportGenerator()
party_data_fetcher = PartyDataFetcher()

@app.get("/")
def root():
    return {"message": "Welcome to the FastAPI Application for Report and Party Data"}

@app.post("/generate-report/")
def generate_report(request: ReportRequest):
    """
    Generates a detailed report for a given topic.
    """
    try:
        report_data = report_generator.generate_detailed_report(request.topic, request.max_results)
        if not report_data["success"]:
            raise HTTPException(status_code=404, detail=report_data["report"])
        save_report(report_data, f"{request.topic.replace(' ', '_').lower()}_report.txt")
        return report_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search/")
def perform_search(query: str, max_results: Optional[int] = 3):
    """
    Performs a search and returns extracted content.
    """
    try:
        search_results = search_and_extract(query, max_results)
        return {"results": search_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process-party/")
def process_party(request: PartyRequest):
    """
    Fetches, analyzes, and stores data for a given Indian political party.
    """
    try:
        party_name = request.party_name
        party_data_fetcher.process_party(party_name)
        return {"message": f"Data for party '{party_name}' processed successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
