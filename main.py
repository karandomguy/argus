from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from modules.report_generator import ReportGenerator, save_report
from modules.search import search_and_extract
from modules.org_data import OrganizationDataFetcher

app = FastAPI()

# Models for input validation
class ReportRequest(BaseModel):
    topic: str
    max_results: Optional[int] = 3

class OrganizationRequest(BaseModel):
    organization_name: str

report_generator = ReportGenerator()
org_data_fetcher = OrganizationDataFetcher()

@app.get("/")
def root():
    return {"message": "Welcome to the FastAPI Application for Report and Organization Data"}

@app.post("/generate-report/")
def generate_report(request: ReportRequest):
    try:
        report_data = report_generator.generate_detailed_report(request.topic, request.max_results)
        if not report_data["success"]:
            raise HTTPException(status_code=404, detail=report_data["report"])
        # Optionally save the report
        save_report(report_data, f"{request.topic.replace(' ', '_').lower()}_report.txt")
        return report_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search/")
def perform_search(query: str, max_results: Optional[int] = 3):
    try:
        search_results = search_and_extract(query, max_results)
        return {"results": search_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process-organization/")
def process_organization(request: OrganizationRequest):
    try:
        org_name = request.organization_name
        org_data_fetcher.process_organization(org_name)
        return {"message": f"Data for organization '{org_name}' processed successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
