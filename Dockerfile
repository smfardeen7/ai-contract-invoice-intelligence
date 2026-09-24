FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY invoice_intelligence invoice_intelligence
COPY examples examples
RUN useradd --create-home app && mkdir var && chown app:app var
USER app
EXPOSE 8050
CMD ["gunicorn", "--bind", "0.0.0.0:8050", "--workers", "2", "invoice_intelligence.wsgi:app"]
