# An isolated CPU-only indexing tool; not built by normal frontend/backend deploys.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
RUN pip install --no-cache-dir mysql-connector-python Pillow pillow-heif opencv-contrib-python-headless open_clip_torch huggingface_hub
WORKDIR /opt/ai
COPY ai/scan.py /opt/ai/scan.py
COPY ai/auto.py /opt/ai/auto.py
ENV HF_HOME=/models OMP_NUM_THREADS=2 AI_THREADS=2 MEDIA_ROOT=/storage
CMD ["python", "/opt/ai/scan.py", "--limit", "100"]
COPY ai/review_auto_resolve.py /opt/ai/review_auto_resolve.py
