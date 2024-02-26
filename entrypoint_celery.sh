#!/bin/sh

celery -A celery_worker.celery worker --autoscale=5,1

