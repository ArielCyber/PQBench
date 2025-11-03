
import pandas
from fastapi import FastAPI, Query
from typing import List

app = FastAPI()

def get_domains_by_attribute(attributes: List[str], excel_file: str = 'domain_data.xlsx') -> dict:
    """
    Reads domain data from an Excel file based on a list of attributes.

    Args:
        attributes: A list of attributes corresponding to sheet names in the Excel file.
        excel_file: The path to the excel file.

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
