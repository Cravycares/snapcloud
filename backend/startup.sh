#!/bin/bash
source /antenv/bin/activate
cd /home/site/wwwroot
python3 -c "from app import init_db; init_db()" 2>&1 | tee -a /home/LogFiles/startup.log
gunicorn --bind=0.0.0.0:${PORT:-8000} --timeout 120 --workers 2 app:app