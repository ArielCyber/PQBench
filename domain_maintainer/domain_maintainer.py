import logging
import sys
import os
import pandas

from fastapi import FastAPI, Query, HTTPException
from typing import List, Dict, Union
import openpyxl
from urllib.parse import urlparse

app = FastAPI()

logging.basicConfig(
    level=os.environ.get("LOGLEVEL", "INFO"),
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


def get_domains_by_attribute(attributes: List[str], excel_file: str = 'domain_data.xlsx') -> Dict[
    str, Union[List[str], str]]:
    """
    Reads domain data from an Excel file based on a list of attributes.

    Args:
        attributes: A list of attributes corresponding to sheet names in the Excel file.
        excel_file: The path to the Excel file.

    Returns:
        A dictionary where each key is an attribute from the input list.
        The corresponding value is either a list of domain strings found in the
        sheet or an error string if the sheet could not be read.
        Example:
        {
            "video": ["youtube.com", "vimeo.com"],
            "news": ["cnn.com", "bbc.com"],
            "invalid_attr": "Error reading sheet: Sheet 'invalid_attr' not found"
        }
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
async def get_domains(attributes: List[str] = Query(...)) -> Dict[str, Union[List[str], str]]:
    """
    API endpoint to get domains for a list of attributes.

    Returns:
        A JSON object where keys are attributes and values are either a list of
        domain strings or an error message.
        Example:
        {
            "video": ["youtube.com", "vimeo.com"],
            "news": ["cnn.com", "bbc.com"]
        }
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
    logging.debug(f"Searching for {domain} in {excel_file} in {attribute}")

    attribute = attribute.lower()
    try:
        # Add a scheme if one is not present
        if not domain.startswith(("http://", "https://")):
            domain_with_scheme = "https://" + domain
        else:
            domain_with_scheme = domain

        parsed_url = urlparse(domain_with_scheme)
        hostname = parsed_url.hostname

        workbook = openpyxl.load_workbook(excel_file)
        if attribute not in workbook.sheetnames:
            raise HTTPException(status_code=404, detail=f"Attribute (worksheet) '{attribute}' not found")

        sheet = workbook[attribute]
        for row in sheet.iter_rows():
            # Check if the row has enough columns before accessing them
            if len(row) > 2 and row[2].value and hostname in row[2].value:
                shadow_class = row[0].value or ""
                play_class = row[1].value or ""
                return {"shadow_class": shadow_class, "play_class": play_class}

        raise HTTPException(status_code=404, detail=f"Domain '{hostname}' not found in attribute '{attribute}'")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Excel file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_button_by_domain/")
async def get_button(domain: str, attribute: str) -> Dict[str, str]:
    """
    API endpoint to get values for a given domain from a specific attribute worksheet.
    """
    logging.info(f"Searching for button in {domain} in {attribute}")
    return get_button_by_domain(domain, attribute)


@app.get("/health")
def health():
    """
    Liveness/readiness probe endpoint.

    Returns:
        ``{"ok": True}`` when the service is up.
    """
    return "ok", 200
