# Domain Maintainer Service

## Overview

The **Domain Maintainer** is a FastAPI-based microservice designed to serve as a read-only interface for domain metadata stored in Excel spreadsheets. It allows other services to query lists of domains categorized by attributes (e.g., "video", "news") and retrieve specific UI configuration data (CSS classes) for individual domains.

It relies on `pandas` for bulk data retrieval and `openpyxl` for specific row-based lookups.

## Project Structure

* **`domain_maintainer.py`**: The core application entry point. Contains the FastAPI app, logic for parsing Excel files, and endpoint definitions.
* **`test_domain_maintainer.py`**: `unittest` suite using `TestClient` to validate the API endpoints against real or mocked data.
* **`domain_data.xlsx`**: (External Dependency) The Excel data source where sheet names correspond to attributes and columns contain metadata.

-----

## 1. Core Architecture

### Data Model

The service treats an Excel file (`domain_data.xlsx`) as a database:

* **Worksheets**: Each sheet represents a category or "attribute" (e.g., `video`, `audio`, `news`).
* **Columns**:
    * **Column 1**: `shadow_class` (UI styling).
    * **Column 2**: `play_class` (UI interaction).
    * **Column 3**: `domain` (The hostname, e.g., `youtube.com`).

### Request Flow

1.  **Request**: Client requests domains by attribute or specific button config by domain.
2.  **File Access**:
    * Bulk requests use `pandas` to load specific sheets.
    * Specific lookups use `openpyxl` to iterate rows and match hostnames.
3.  **Parsing**: URLs are normalized (schemes added/stripped) to extract the hostname.
4.  **Response**: JSON data is returned with the requested metadata.

-----

## 2. API Reference

### `GET /get_domains/`

Retrieves a list of all domains associated with the provided attributes.

**Parameters:**

* `attributes` (Query Param, List[str]): A list of attributes to fetch (e.g., `?attributes=video&attributes=news`).

**Response Example:**

```json
{
  "video": ["youtube.com", "vimeo.com"],
  "news": ["cnn.com", "bbc.com"],
  "invalid_attr": "Error reading sheet: Sheet 'invalid_attr' not found"
}
```

### `GET /get_button_by_domain/`

Retrieves the UI configuration (shadow and play classes) for a specific domain within a specific attribute category.

**Parameters:**

* `domain` (Query Param, str): The domain to search for (e.g., `youtube.com` or `https://youtube.com`).
* `attribute` (Query Param, str): The category sheet to search in (e.g., `video`).

**Response Example:**

```json
{
  "shadow_class": "shadow-lg",
  "play_class": "btn-play-red"
}
```

### `GET /health`

Returns `"ok", 200` to indicate the service is running.

-----

## 3. Key Logic & Internals

### Domain Parsing

To ensure consistent matching, the service normalizes inputs in `get_button_by_domain`:

1.  Checks if the input string starts with `http://` or `https://`.
2.  If missing, appends `https://`.
3.  Uses `urllib.parse.urlparse` to extract the `hostname`.
4.  Matches this hostname against the 3rd column of the Excel sheet.

### Excel Handling Strategies

The service uses two different libraries depending on the operation type:

1.  **Bulk Retrieval (`pandas`)**:

    * Used in `get_domains_by_attribute`.
    * Reads the entire sheet efficiently.
    * Extracts the 3rd column (`iloc[:, 2]`) and drops `NaN` values.

2.  **Specific Lookup (`openpyxl`)**:

    * Used in `get_button_by_domain`.
    * Loads the workbook and specific sheet.
    * Iterates row-by-row (`sheet.iter_rows()`) to find a match.
    * Returns values from the 1st and 2nd columns upon finding a match in the 3rd.

-----

## 4. Error Handling

* **404 Not Found**: Returned if the Excel file is missing, the requested Attribute (Sheet) does not exist, or the Domain is not found in that sheet.
* **500 Internal Server Error**: Returned for generic file parsing errors.

-----

## 5. Testing

The project uses `unittest` for integration testing.

### Running Tests

Tests the API endpoints using `FastAPI.testclient`.

```bash
python -m unittest test_domain_maintainer.py
```
