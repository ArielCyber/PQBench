FROM python:3.12-slim
WORKDIR /app

# If you have requirements.txt, use this:
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY router.py /app/
COPY static/ /app/static/

EXPOSE 5000
CMD ["python", "router.py"]
