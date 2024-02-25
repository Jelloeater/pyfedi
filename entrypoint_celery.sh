#!/bin/sh

celery -A celery_worker.celery worker
