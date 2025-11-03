import pandas
from fastapi import FastAPI, Query, HTTPException
from typing import List, Dict
import openpyxl

app = FastAPI()


def get_domains_by_attribute(attributes: List[str], excel_file: str = 'domain_data.xlsx') -> dict:
    """
    Reads domain data from an Excel file based on a list of attributes.

    Args:
        attributes: A list of attributes corresponding to sheet names in the Excel file.
        excel_file: The path to the Excel file.

    Returns:
        A dictionary where keys are attributes and values are lists of domain names.
    """
    all_domains = {}

    for attribute in attributes:
        try:
            # Read the specified sheet, skipping the first row
            df = pandas.read_excel(excel_file, sheet_name=attribute, header=0)
            # Extract the third column and remove NaN values
            domains = df.iloc[:, 2].dropna().tolist()
            all_domains[attribute] = domains
        except Exception as e:
            # Handle cases where the sheet might not exist
            all_domains[attribute] = f"Error reading sheet: {e}"

    return all_domains


@app.get("/get_domains/")
async def get_domains(attributes: List[str] = Query(...)):
    """
    API endpoint to get domains for a list of attributes.
    """
    return get_domains_by_attribute(attributes)


def get_button_by_domain(domain: str, attribute: str, excel_file: str = 'domain_data.xlsx') -> Dict[str, str]:
    """
    Searches for a domain in the third column of a specific worksheet (attribute)
    and returns the corresponding values from the first and second columns.

    Args:
        domain: The domain to search for.
        attribute: The name of the worksheet to search in.
        excel_file: The path to the Excel file.

    Returns:
        A dictionary containing the values from the first and second columns,
        or raises an HTTPException if the domain or attribute is not found.
    """
    try:
        workbook = openpyxl.load_workbook(excel_file)
        if attribute not in workbook.sheetnames:
            raise HTTPException(status_code=404, detail=f"Attribute (worksheet) '{attribute}' not found")

        sheet = workbook[attribute]
        for row in sheet.iter_rows():
            # Check if the row has enough columns before accessing them
            if len(row) > 2 and row[2].value == domain:
                return {"value_col_1": row[0].value, "value_col_2": row[1].value}

        raise HTTPException(status_code=404, detail=f"Domain '{domain}' not found in attribute '{attribute}'")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Excel file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_button_by_domain/")
async def get_button(domain: str, attribute: str):
    """
    API endpoint to get values for a given domain from a specific attribute worksheet.
    """
    return get_button_by_domain(domain, attribute)


@app.get("/health")
def health():
    """
    Liveness/readiness probe endpoint.

    Returns:
        ``{"ok": True}`` when the service is up.
    """
    return "ok", 200
