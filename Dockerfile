FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server/ ./server/

# Railway uses PORT env variable
ENV PORT=8001

# Run the server - use shell form to expand $PORT
CMD python -m server.server --host 0.0.0.0 --port $PORT
