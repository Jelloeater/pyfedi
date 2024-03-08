# Contents

* [Setup Database](#setup-database)   
* [Install Python Libraries](#install-python-libraries)      
* [Install additional requirements](#install-additional-requirements)      
* [Setup pyfedi](#setup-pyfedi)
* [Setup .env file](#setup-env-file)
* [Initialise Database and Setup Admin account](#initialise-database-and-setup-admin-account)
* [Run the app](#run-the-app)
* [Database Management](#database-management)
* [Keeping your local instance up to date](#keeping-your-local-instance-up-to=date)
* [Running PieFed in production](#running-piefed-in-production)
* [Pre-requisites for Mac OS](#pre-requisites-for-mac-os)
* [Notes for Windows (WSL2)](#notes-for-windows-wsl2)        
* [Notes for Pip Package Management](#notes-for-pip-package-management)

<div id="setup-database"></div>

## Setup Database

#### Install postgresql 16            

For installation environments that use 'apt' as a package manager:

`sudo apt install ca-certificates pkg-config`             
`wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -`            
`sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" >> /etc/apt/sources.list.d/pgdg.list'`          
`sudo apt update`           
`sudo apt install libpq-dev postgresql`            

#### Create new DB user

Choose a username and password. To use 'pyfedi' for both:     
`sudo -iu postgres psql -c "CREATE USER pyfedi WITH PASSWORD 'pyfedi';"`      

#### Create new database

Choose a database name, owned by your new user. For a database called and owned by 'pyfedi':      
`sudo -iu postgres psql -c "CREATE DATABASE pyfedi WITH OWNER pyfedi;"`    

<div id="install-python-libraries"></div>

## Install Python Libraries

[Pre-requisites for Mac OS](#pre-requisites-for-mac-os)         
[Notes for Windows (WSL2)](#notes-for-windows-wsl2)        

For installation environments that use 'apt' as a package manager:   
`sudo apt install python3-pip python3-venv python3-dev python3-psycopg2` 


<div id="install-additional-requirements"></div>

## Install additional requirements

For installation environments that use 'apt' as a package manager:        
`sudo apt install redis-server`       
`sudo apt install git`     
`sudo apt install tesseract-ocr`

<div id="setup-pyfedi"></div>

## Setup PyFedi

#### Clone PyFedi            
`git clone https://codeberg.org/rimu/pyfedi.git`

#### cd into pyfedi, set up and enter virtual environment
`cd pyfedi`            
`python3 -m venv ./venv`           
`source venv/bin/activate`

#### Use pip to install requirements               
`pip install wheel`               
`pip install -r requirements.txt`       
(see [Notes for Windows (WSL2)](#windows-wsl2) if appropriate)        

<div id="setup-env-file"></div>

## Setup .env file
Copy env.sample to .env

Edit .env to suit your server.  

Using the same username, password, and database name as used when setting up database, set the connection up, something like this:
    
    DATABASE_URL=postgresql+psycopg2://username:password@localhost/database_name
    

Also change SECRET_KEY to some random sequence of numbers and letters.

SERVER_NAME should be the domain of the site/instance. Use 127.0.0.1:5000 during development unless using ngrok.

RECAPTCHA_PUBLIC_KEY and RECAPTCHA_PRIVATE_KEY can be generated at https://www.google.com/recaptcha/admin/create.

CACHE_TYPE can be 'FileSystemCache' or 'RedisCache'. FileSystemCache is fine during development (set CACHE_DIR to /tmp/piefed or /dev/shm/piefed)
while RedisCache should be used in production. If using RedisCache, set CACHE_REDIS_URL to redis://localhost:6379/1

CELERY_BROKER_URL is similar to CACHE_REDIS_URL but with a different number on the end: 'redis://localhost:6379/0'

MAIL_* is for sending email using a SMTP server. Leave MAIL_SERVER empty to send email using AWS SES instead.

AWS_REGION is the name of the AWS region where you chose to set up SES, if using SES. [SES credentials are stored in ~/.aws/credentials](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html). That file has a format like

```
[default]
aws_access_key_id = JKJHER*#KJFFF
aws_secret_access_key = /jkhejhkrejhkre
region=ap-southeast-2
```
You can also [use environment variables](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html#environment-variables) if you prefer.

Test email sending by going to https://yourdomain/test_email. It will try to send an email to the current user's email address.
If it does not work check the log file at logs/pyfedi.log for clues.

<div id="initialise-database-and-setup-admin-account"></div>

## Initialise database, and set up admin account
`flask init-db`       
(choose a new username, email address, and password for your PyFedi admin account)

<div id="run-the-app"></div>

## Run the app             
`flask run`          
(open web browser at http://127.0.0.1:5000)          
(log in with username and password from admin account)

<div id="database-management"></div>

## Database Management

In future if you use git pull and notice some new files in migrations/versions/*, you need to do:    

`source venv/bin/activate`   (if not already in virtual environment)  
`flask db upgrade`

#### For Database changes:

create a migration based on recent changes to app/models.py:        
`flask db migrate -m "users table"`     
run migrations:         
`flask db upgrade`     

<div id="keeping-your-local-instance-up-to=date"></div>

## Keeping your local instance up to date

In a development environment, all you need to do is

`git pull`  
`flask db upgrade`

In production, celery and flask run as background services so they need to be restarted manually. Run the `./deploy.sh` script
to easily restart services at the same time as pulling down changes from git, etc.

<div id="federation-during-development"></div>

## Federation during development

Federation doesn't work without SSL, without a domain name or without your server being accessible from outside your network. So, when running on http://127.0.0.1:5000 you have none of those.

The site will still run without federation. You can create local communities and post in them...

My way around this is to use ngrok.com, which is a quick and simple way to create a temporary VPN with a domain and SSL. The free plan comes with ephermeral domain names that change every few days, which will break federation, or one randomly-named static domain that will need re-launching every few days. $10 per month will get you https://yourwhatever.ngrok.app which won't change. 

Once you have ngrok working, edit the .env file and change the SERVER_NAME variable to your new domain name. 

<div id="running-piefed-in-production"></div>

## Running PieFed in production


Copy celery_worker.default.py to celery_worker.py. Edit DATABASE_URL and SERVER_NAME to have the same values as in .env.

Edit gunicorn.conf.py and change worker_tmp_dir if needed.

You will want to [tune PostgreSQL](https://pgtune.leopard.in.ua/). [More on this](https://www.enterprisedb.com/postgres-tutorials/how-tune-postgresql-memory).
If you have more than 4 GB of RAM, consider [turning on 'huge pages'](https://www.percona.com/blog/why-linux-hugepages-are-super-important-for-database-servers-a-case-with-postgresql/)
also [see this](https://pganalyze.com/blog/5mins-postgres-tuning-huge-pages).

(PgBouncer)[https://www.pgbouncer.org] can be helpful in a high traffic situation.

<div id="background-services"></div>

### Background services


Gunicorn and Celery need to run as background services:

#### Gunicorn

Create a new file:

    sudo nano /etc/systemd/system/pyfedi.service

Add the following to the new file, altering paths as appropriate for your install location

    [Unit]
    Description=Gunicorn instance to serve PieFed application
    After=network.target
    
    [Service]
    User=rimu
    Group=rimu
    WorkingDirectory=/home/rimu/pyfedi/
    Environment="PATH=/home/rimu/pyfedi/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin"
    ExecStart=/home/rimu/pyfedi/venv/bin/gunicorn --config gunicorn.conf.py --preload pyfedi:app
    ExecReload=/bin/kill -HUP $MAINPID
    Restart=always
    
    
    [Install]
    WantedBy=multi-user.target

#### Celery

Create another file:

    sudo nano /etc/systemd/system/celery.service

Add the following, altering as appropriate

    [Unit]
    Description=Celery Service
    After=network.target
    
    [Service]
    Type=forking
    User=rimu
    Group=rimu
    EnvironmentFile=/etc/default/celeryd
    WorkingDirectory=/home/rimu/pyfedi
    ExecStart=/bin/sh -c '${CELERY_BIN} multi start -A ${CELERY_APP} ${CELERYD_NODES} --pidfile=${CELERYD_PID_FILE} \
      --logfile=${CELERYD_LOG_FILE} ${CELERYD_OPTS}'
    ExecStop=/bin/sh -c '${CELERY_BIN} multi stopwait ${CELERYD_NODES} --pidfile=${CELERYD_PID_FILE}'
    ExecReload=/bin/sh -c '${CELERY_BIN} multi restart -A ${CELERY_APP} ${CELERYD_NODES} --pidfile=${CELERYD_PID_FILE} \
      --logfile=${CELERYD_LOG_FILE} ${CELERYD_OPTS}'
    
    [Install]
    WantedBy=multi-user.target

Create another file:

    sudo nano /etc/default/celeryd

Contents (change paths to suit):

    # The names of the workers. This example creates one workers
    CELERYD_NODES="worker1"
    
    # The name of the Celery App, should be the same as the python file
    # where the Celery tasks are defined
    CELERY_APP="celery_worker.celery"
    
    # Log and PID directories
    CELERYD_LOG_FILE="/var/log/celery/%n%I.log"
    CELERYD_PID_FILE="/dev/shm/celery/%n.pid"
    
    # Log level
    CELERYD_LOG_LEVEL=INFO
    
    # Path to celery binary, that is in your virtual environment
    CELERY_BIN=/home/rimu/pyfedi/venv/bin/celery
    CELERYD_OPTS="--autoscale=5,1"

#### Enable and start background services

    sudo systemctl enable pyfedi.service
    sudo systemctl enable celery.service

    sudo systemctl start pyfedi.service
    sudo systemctl start celery.service

Check status of services:

    sudo systemctl status pyfedi.service
    sudo systemctl status celery.service

Inspect log files at:

    /var/log/celery/*
    /var/log/nginx/*
    /your_piefed_installation/logs/pyfedi.log


### Nginx

You need a reverse proxy that sends all traffic to port 5000. Something like:

    upstream app_server {
        # fail_timeout=0 means we always retry an upstream even if it failed
        # to return a good HTTP response

        # for UNIX domain socket setups
        # server unix:/tmp/gunicorn.sock fail_timeout=0;

        # for a TCP configuration
        server 127.0.0.1:5000 fail_timeout=0;
        keepalive 4;
    }

    server {
        server_name piefed.social
        root /whatever

        keepalive_timeout 5;
        ssi off;

        location / {
            # Proxy all requests to Gunicorn
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Host $http_host;
            proxy_redirect off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_pass http://app_server;
            ssi off;
        }
    }

The above is not a complete configuration - you will want to add more settings for SSL, etc.

### Cron tasks


To send email reminders about unread notifications, put this in a new file under /etc/cron.d

```
1 */6 * * * rimu cd /home/rimu/pyfedi && /home/rimu/pyfedi/email_notifs.sh
```

Change /home/rimu/pyfedi to the location of your installation and change 'rimu' to the user that piefed runs as.

Once a week or so it's good to run remove_orphan_files.sh to save disk space:

```
5 4 * * 1 rimu cd /home/rimu/pyfedi && /home/rimu/pyfedi/remove_orphan_files.sh
```

### Email

Email can be sent either through SMTP or Amazon web services (SES). SES is faster but PieFed does not send much
email so it probably doesn't matter which method you choose.

#### AWS SES

PieFed uses Amazon's "boto3" module to connect to SES. Boto3 needs to log into AWS and that can be set up using a file
at ~/.aws/credentials or environment variables. Details at https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html.

In your .env you need to set the AWS region you're using for SES. Something like AWS_REGION = 'ap-southeast-2'.

#### SMTP

To use SMTP you need to set all the MAIL_* environment variables in you .env file. See env.sample for a list of them.

#### Testing email

You need to set MAIL_FROM in .env to some email address.

Log into Piefed then go to https://yourdomain/test_email to trigger a test email. It will use SES or SMTP depending on
which environment variables you defined in .env. If MAIL_SERVER is empty it will try SES. Then if AWS_REGION is empty it'll
silently do nothing.

---


<div id="pre-requisites-for-mac-os"></div>

## Pre-requisites for Mac OS

#### Install Python Version Manager (pyenv)
see this site: https://opensource.com/article/19/5/python-3-default-mac
    
`brew install pyenv`

#### Install Python3 version and set as default (with pyenv) 

`pyenv install 3.8.6`  
`pyenv global 3.7.3`

Note..
You may see this error when running `pip install -r requirements.txt` in regards to psycopg2:
    
    ld: library not found for -lssl
    clang: error: linker command failed with exit code 1 (use -v to see invocation)
    error: command 'clang' failed with exit status 1

If this happens try installing openssl...
Install openssl with brew install openssl if you don't have it already.
    
`brew install openssl`
    
Add openssl path to LIBRARY_PATH :
    
    export LIBRARY_PATH=$LIBRARY_PATH:/usr/local/opt/openssl/lib/
    
---

<div id="notes-for-windows-wsl2"></div>

## Notes for Windows (WSL 2 - Ubuntu 22.04 LTS - Python 3.9.16)

**Important:**
    Python 3.10+ or 3.11+ may cause some package or compatibility errors. If you are having issues installing packages from
    requirements.txt, try using Python 3.8 or 3.9 instead with pyenv (https://github.com/pyenv/pyenv).
    Follow all the setup instructions in the pyenv documentation and setup any version of either Python 3.8 or 3.9.
    If you are getting installation errors or missing packages with pyenv, run 

`sudo apt update`
`sudo apt install build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev curl libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev llvm`

#### Install Python 3, pip, and venv

`sudo apt-get update`
`sudo apt-get upgrade`
`sudo apt-get install python3 python3-pip ipython3 libpq-dev python3-psycopg2 python3-dev build-essential redis-server`
`sudo apt-get install python3-venv`

#### Setup venv first before installing other packages
**Note: **
    (Replace <3.9> with your version number if you are using another version of Python, 
    e.g. 'sudo apt-get install python3.10-venv' for Python 3.10. Repeat for the rest of the instructions below.)

`python3.9 -m venv ./venv`   
`source venv/bin/activate`

Make sure that your venv is also running the correct version of pyenv. You may need to re-setup venv if you setup venv before pyenv.

Follow the package installation instructions above to get the packages

`python3.9 -m pip install --upgrade pip setuptools wheel`   
`pip install -r requirements.txt`

<div id="notes-for-pip-package-management"></div>

---

## Notes for Pip Package Management:

make sure you have 'wheel' installed:
`pip install wheel`
    
install packages from a file:
`pip install -r requirements.txt`

dump currently installed packages to file:
`pip freeze > requirements.txt`

upgrade a package:
`pip install --upgrade <package_name>`

