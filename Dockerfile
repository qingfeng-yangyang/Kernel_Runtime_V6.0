FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY main.py ./
RUN pip install --no-cache-dir -e ".[preproduction]"
ENV PYTHONPATH=/app/src CREATE_HTTP_APP=true
EXPOSE 8000
CMD ["uvicorn", "kernel_runtime.production.api:app", "--host", "0.0.0.0", "--port", "8000"]
