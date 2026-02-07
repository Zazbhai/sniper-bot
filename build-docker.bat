@echo off
echo Building Docker image...
docker build -t flipkart-automation .
echo.
echo Build complete! Run with:
echo docker run -p 5000:5000 flipkart-automation









