#!/bin/bash
date > updated.txt

sudo systemctl stop celery.service
git pull
source venv/bin/activate
flask db upgrade
sudo systemctl start celery.service
sudo systemctl restart pyfedi.service
