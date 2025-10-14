# Use an official lightweight Python image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file
COPY requirements.txt .

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code (bot.py, quizzes folder, etc.)
COPY . .

# Command to run the bot when the container starts
CMD ["python", "bot.py"]
