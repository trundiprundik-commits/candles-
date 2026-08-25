#!/bin/bash
# На сервере, из папки проекта: bash deploy.sh
set -e
cd "$(dirname "$0")"
git pull
docker-compose up -d --build
docker-compose ps
echo "Готово."
