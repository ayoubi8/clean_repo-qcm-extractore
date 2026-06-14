FROM python:3.11-slim

# System dependencies needed by PDF/image processing modules
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app

# Install Python dependencies first (better Docker layer caching)
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application code
COPY api/ /app/
COPY modules/ /app/modules/
COPY suport/ /app/suport/
COPY batch_config.yaml /app/batch_config.yaml
COPY admin.env /app/admin.env

# Create writable output directory for ephemeral pipeline I/O
RUN mkdir -p /app/output && chmod 777 /app/output

# HF Spaces runs containers as user 1000
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER 1000

# HF Spaces requires port 7860
EXPOSE 7860

# No --reload in production
CMD ["uvicorn", "real_api:app", "--host", "0.0.0.0", "--port", "7860"]

