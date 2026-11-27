# Image minimale : Python standard uniquement, aucune dépendance à installer.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml run.py ./
COPY src ./src
RUN useradd --system --no-create-home appuser && mkdir /data && chown appuser /data
USER appuser
ENV DELIVERYOPT_DB=/data/app.db DELIVERYOPT_HOST=0.0.0.0 DELIVERYOPT_PORT=8000
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ['DELIVERYOPT_PORT']+'/api/health',timeout=3)"
CMD ["python", "run.py", "serve"]
