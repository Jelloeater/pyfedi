#!/bin/bash
date > updated.txt

git pull
sudo systemctl restart pyfedi.service
