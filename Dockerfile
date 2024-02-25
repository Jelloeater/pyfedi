# syntax=docker/dockerfile:1.4
FROM --platform=$BUILDPLATFORM python:3-alpine AS builder

WORKDIR /app

RUN apk update
RUN apk add pkgconfig
RUN apk add --virtual build-deps gcc python3-dev musl-dev

COPY requirements.txt /app
RUN pip3 install -r requirements.txt
RUN pip3 install gunicorn

COPY . /app
RUN chmod u+x ./entrypoint.sh
RUN chmod u+x ./entrypoint_celery.sh

ENTRYPOINT ["./entrypoint.sh"]


