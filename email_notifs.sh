#!/bin/bash

source venv/bin/activate
export FLASK_APP=pyfedi.py
flask send_missed_notifs
