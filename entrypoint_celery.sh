#!/bin/sh

celery multi start -A celery_worker_local.celery worker1
