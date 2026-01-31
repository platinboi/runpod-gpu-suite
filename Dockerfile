# GPU-optimized Docker image for RunPod Serverless
# Includes CUDA for AI inference and NVENC for FFmpeg encoding

FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies including FFmpeg with NVENC support
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1-mesa-glx \
    fonts-dejavu-core \
    fonts-noto-color-emoji \
    fontconfig \
    tzdata \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create custom fonts directory
RUN mkdir -p /usr/share/fonts/truetype/custom

# Set working directory
WORKDIR /app

# Copy fonts first (for font installation)
COPY fonts/ /app/fonts/

# Install custom fonts
RUN cp /app/fonts/*.ttf /usr/share/fonts/truetype/custom/ && \
    fc-cache -f -v

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the birefnet-general model to avoid cold start delay
# This bakes the model into the Docker image (~973MB)
RUN python -c "from rembg import new_session; session = new_session('birefnet-general'); print('Model loaded successfully')"

# Set Python path
ENV PYTHONPATH=/app/src

# Create temp directory
RUN mkdir -p /app/temp

# Copy source code directly into image
COPY src/ /app/src/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "print('healthy')" || exit 1

# Run handler directly
CMD ["python", "-u", "/app/src/handler.py"]
