FROM python:3.10

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Expose port for Koyeb health checks
EXPOSE 8080

# Run the bot + webserver
CMD ["python", "bot.py"]

