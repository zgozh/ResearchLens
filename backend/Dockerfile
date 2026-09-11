FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 迁移所需：alembic.ini + migrations（启动时 run_migrations 依赖）
COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

# 运行时数据目录（上传/源文件/资产/runtime 配置，由 backend-data 卷挂载）
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
