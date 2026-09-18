FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /e2e

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 一次性验收：跑完即退出，退出码即验收结果
CMD ["pytest", "-v", "--tb=short"]
