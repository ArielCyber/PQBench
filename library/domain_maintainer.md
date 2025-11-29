# Domain Maintainer Service

This service is a FastAPI-based application that serves as a data provider for domain configuration. It reads from a backend Excel file (`domain_data.xlsx`) to supply clients with lists of domains categorized by attributes (e.g., "video", "news") and specific UI element selectors for those domains.

# Overview

The service exposes endpoints to:
1.  **List Domains:** Retrieve lists of domains belonging to specific categories (Excel sheets).
2.  **Get UI Config:** Lookup specific configuration details (shadow DOM classes, play buttons) for a given domain.

This service is designed to support automation or crawling tools by providing the specific targets and interaction selectors needed for different web pages.

# Prerequisites

* **Python 3.8+**
* **Dependencies:**
    * `fastapi`
    * `uvicorn` (for serving)
    * `pandas` (for reading Excel)
    * `openpyxl` (Excel engine)

# Configuration

The service relies on a local Excel file named `domain_data.xlsx` located in the same directory.

**Excel Structure:**
* **Sheet Name:** Represents the `attribute` (e.g., "video", "shopping").
* **Columns:**
    * **Column 1:** Shadow Class (CSS selector/ID).
    * **Column 2:** Play Button (CSS selector/ID).
    * **Column 3:** Domain Name (e.g., `https://youtube.com`).

# Usage

## API Endpoints

### 1. Get Domains by Attribute
Retrieves all domains listed under specific categories.

**Endpoint:** `GET /get_domains/`

**Parameters:**
* `attributes` (Query Param, List[str]): The names of the Excel sheets to query.

**Example Request:**
`GET http://localhost:8000/get_domains/?attributes=video&attributes=news`

**Example Response:**
```json
{
  "video": [
    "youtube.com",
    "vimeo.com"
  ],
  "news": [
    "cnn.com",
    "bbc.com"
  ],
  "invalid_category": "Error reading sheet: ..."
}
```

### 2. Get Button Configuration
Retrieves specific UI selectors (shadow class, play button) for a specific domain within a category.

**Endpoint:** `GET /get_button_by_domain/`

**Parameters:**
* `domain` (Query Param): The domain to search for (e.g., `youtube.com`).
* `attribute` (Query Param): The category/sheet name (e.g., `video`).

**Example Request:**
`GET http://localhost:8000/get_button_by_domain/?domain=youtube.com&attribute=video`

**Example Response:**
```json
{
  "shadow_class": "ytd-app",
  "play_button": "#play-button"
}
```

### 3. Health Check
Liveness probe to ensure the service is running.

**Endpoint:** `GET /health`

**Response:**
`["ok", 200]`

# Flow

1.  **Initialization:** The service starts and checks for `domain_data.xlsx`.
2.  **Discovery:** A client (e.g., a traffic generator) calls `/get_domains/` to find out which domains it needs to visit for a specific category (e.g., `video`).
3.  **Action Lookup:** For each domain, the client calls `/get_button_by_domain/` to determine how to interact with the page (e.g., which button to click to start a video).
4.  **Execution:** The service parses the Excel sheet, finds the matching row for the domain, and returns the selectors (`shadow_class`, `play_button`).
