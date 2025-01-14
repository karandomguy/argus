# Argus Project

Argus is a Python-based AI Research Agent designed to assist with web search, report generation, and organizational data management. Built on the open-source Llama 3.2 LLM, Argus offers advanced NLP capabilities and integrates seamlessly with tools like FastAPI, Google Custom Search Engine, and NewsAPI. The project is engineered for accuracy, completeness, and usability, providing reliable data insights for diverse research needs.

---

## Features

- **Web Search and Report Generation:**
  - Performs web searches on any topic and generates detailed, well-structured reports.
  - Includes source links for all referenced information to ensure transparency.
  - Uses BeautifulSoup and spaCy for intelligent content parsing and processing.
- **Organizational Data Fetch and Storage:**
  - Fetches open-source details about political organizations, including news, posts, and wiki data.
  - Retrieves detailed information about the organization's leaders and members.
  - Stores all data in an SQLite database for future reference.
- **FastAPI Framework:** Provides a RESTful API for intuitive interaction.
---

## Installation and Setup

### Prerequisites
- Python 3.8 or later.
- API keys for:
  - Google CSE
  - NewsAPI
  - Groq API (for NLP-driven report generation).

### Steps to Install

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/karandomguy/argus.git
   cd argus
   ```

2. **Install Dependencies:**
   Use the `requirements.txt` file to install all necessary packages:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set Environment Variables:**
   Create a `.env` file in the project root and add your API keys:
   ```plaintext
   GOOGLE_API_KEY=your_google_api_key
   GOOGLE_CSE_ID=your_cse_id
   NEWS_API_KEY=your_news_api_key
   GROQ_API_KEY=your_groq_api_key
   ```

4. **Download NLP Models:**
   Install required NLP models for spaCy and NLTK:
   ```bash
   python -m spacy download en_core_web_sm
   python -m nltk.downloader punkt
   ```
---

## How to Use

### 1. Start the Application
Launch the FastAPI server by running:
```bash
uvicorn main:app --reload
```
The API will be accessible at `http://127.0.0.1:8000`.

### 2. API Endpoints

#### **Root Endpoint**
- **URL:** `/`
- **Method:** GET
- **Description:** Verifies that the application is running.
- **Response:**
  ```json
  {
    "message": "Welcome to the FastAPI Application for Report and Organization Data"
  }
  ```

#### **Generate Report**
- **URL:** `/generate-report/`
- **Method:** POST
- **Description:** Generates a detailed report on a given topic.
- **Request Body:**
  ```json
  {
    "topic": "Artificial Intelligence",
    "max_results": 5
  }
  ```
- **Response:**
  ```json
  {
    "success": true,
    "report": "<Detailed report content>",
    "metadata": {
      "topic": "Artificial Intelligence",
      "sources": 5,
      "source_domains": ["example.com", "anotherexample.com"],
      "total_content_length": 1200
    }
  }
  ```

#### **Perform Search**
- **URL:** `/search/`
- **Method:** POST
- **Description:** Executes a web search and extracts relevant content.
- **Request Parameters:**
  - `query`: Search term.
  - `max_results`: Maximum number of results (optional, default is 3).
- **Response:**
  ```json
  {
  "title": "Introduction to Artificial Intelligence (AI) | Coursera",
  "link": "https://www.coursera.org/learn/introduction-to-ai",
  "snippet": "The course includes hands-on labs and a project, providing an opportunity to explore AI's use cases and applications. You will also hear from expert ...",
  "domain": "www.coursera.org",
  "extracted_content": "Full content extracted from the webpage...",
  "metadata": {
    "title": "Introduction to Artificial Intelligence (AI) | Coursera",
    "length": 1503,
    "url": "https://www.coursera.org/learn/introduction-to-ai",
    "domain": "www.coursera.org"
  },
  "error": null
  }
  ```

#### **Process Organization**
- **URL:** `/process-organization/`
- **Method:** POST
- **Description:** Processes organizational data by fetching Wikipedia and NewsAPI data.
- **Request Body:**
  ```json
  {
    "organization_name": "BJP"
  }
  ```
- **Response:**
  ```json
  {
    "message": "Data for organization 'BJP' processed successfully."
  }
  ```

---

## Examples of Inputs and Outputs

### Example 1: Generate a Report
- **Input:**
  ```json
  {
    "topic": "Quantum Computing",
    "max_results": 3
  }
  ```
- **Output:** A detailed report with sections like Executive Summary, Key Findings, and References.

### Example 2: Perform a Search
- **Input:**
  ```json
  {
    "query": "Climate Change",
    "max_results": 2
  }
  ```
- **Output:**
  ```json
  {
    "results": [
      {
        "title": "What is Climate Change?",
        "link": "https://example.com/climate",
        "snippet": "Climate change refers to...",
        "extracted_content": "Full content here",
        "metadata": { "length": 1000 }
      }
    ]
  }
  ```

---

## Technical Details

### Directory Structure
```
Argus/
├── main.py                # Entry point for the FastAPI application
├── modules/               # Contains project modules
│   ├── org_data.py        # Manages organization data
│   ├── report_generator.py # Generates reports using Groq API
│   └── search.py          # Performs web searches and content extraction
├── requirements.txt       # Python dependencies
└── README.md              # Project documentation
```

---

## License
This project is licensed under the MIT License. See the LICENSE file for details.

---

## Contributing
Contributions are welcome! Please fork the repository, make your changes, and submit a pull request for review.

---

## Acknowledgments
- Google Custom Search Engine API
- NewsAPI
- Groq API
- spaCy and NLTK for NLP processing
- BeautifulSoup for web scraping

---
