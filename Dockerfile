FROM python:3.12-slim
WORKDIR /srv
COPY pyproject.toml .
COPY app app
COPY eval eval
COPY static static
COPY data data
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
