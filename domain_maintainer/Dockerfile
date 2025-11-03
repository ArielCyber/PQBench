# Use an official lightweight Python image.
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code and data file into the container
COPY domain_maintainer.py .
COPY domain_data.xlsx .

# Expose the port the app runs on
EXPOSE 5010

# Command to run the application
# Use uvicorn to run the FastAPI application
# --host 0.0.0.0 makes it accessible from outside the container
CMD ["uvicorn", "domain_maintainer:app", "--host", "0.0.0.0", "--port", "5010"]
