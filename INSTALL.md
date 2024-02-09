Mac OS
---
Install Python Version Manager (pyenv)
see this site: https://opensource.com/article/19/5/python-3-default-mac
    
    brew install pyenv

Install Python3 version and set as default (with pyenv) 

    pyenv install 3.8.6
    pyenv global 3.7.3

Note..
You may see this error when running `pip install -r requirements.txt` in regards to psycopg2:
    
    ld: library not found for -lssl
    clang: error: linker command failed with exit code 1 (use -v to see invocation)
    error: command 'clang' failed with exit status 1

If this happens try installing openssl...
Install openssl with brew install openssl if you don't have it already.
    
    brew install openssl
    
Add openssl path to LIBRARY_PATH :
    
    export LIBRARY_PATH=$LIBRARY_PATH:/usr/local/opt/openssl/lib/

Linux
---
install these additional packages

```sudo apt install python3-psycopg2 libpq-dev python3-dev redis-server```


Pip Package Management:
---

make sure you have 'wheel' installed:
    ```pip install wheel```

dump currently installed packages to file:
    ```pip freeze > requirements.txt```

install packages from a file:
    ```pip install -r requirements.txt```

upgrade a package:
    ```pip install --upgrade <package_name>```


---


Postgresql Setup:
---
installing postgresql https://www.digitalocean.com/community/tutorials/how-to-install-and-use-postgresql-on-ubuntu-18-04



Windows (WSL 2 - Ubuntu 22.04 LTS - Python 3.9.16)
---
**Important**
    Python 3.10+ or 3.11+ may cause some package or compatibility errors. If you are having issues installing packages from
    requirements.txt, try using Python 3.8 or 3.9 instead with pyenv (https://github.com/pyenv/pyenv).
    Follow all the setup instructions in the pyenv documentation and setup any version of either Python 3.8 or 3.9.
    If you are getting installation errors or missing packages with pyenv, run 

        sudo apt update
        sudo apt install build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev curl libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev llvm

Install Python 3, pip, and venv

    sudo apt-get update
    sudo apt-get upgrade
    sudo apt-get install python3 python3-pip ipython3 libpq-dev python3-psycopg2 python3-dev build-essential redis-server
    sudo apt-get install python3-venv

Setup venv first before installing other packages
**Note**
    (Replace <3.9> with your version number if you are using another version of Python, 
    e.g. 'sudo apt-get install python3.10-venv' for Python 3.10. Repeat for the rest of the instructions below.)

        python3.9 -m venv ./venv
        source venv/bin/activate

Make sure that your venv is also running the correct version of pyenv. You may need to re-setup venv if you setup venv before pyenv.

Follow the package installation instructions above to get the packages

    python3.9 -m pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt

Continue with the .env setup and "Run API" sections below.


---


.env setup
---
Copy env.sample to .env

Edit .env to suit your server. Set the database connection up, something like this
    
    DATABASE_URL=postgresql+psycopg2://username:password@localhost/database_name

Also change SECRET_KEY to some random sequence of numbers and letters.

SERVER_NAME should be the domain of the site/instance. Use 127.0.0.1:5000 during development unless using ngrok.

RECAPTCHA_PUBLIC_KEY and RECAPTCHA_PRIVATE_KEY can be generated at https://www.google.com/recaptcha/admin/create.

CACHE_TYPE can be 'FileSystemCache' or 'RedisCache'. FileSystemCache is fine during development (set CACHE_DIR to /tmp/piefed or /dev/shm/piefed)
while RedisCache should be used in production. If using RedisCache, set CACHE_REDIS_URL to redis://localhost:6379/1

CELERY_BROKER_URL is similar to CACHE_REDIS_URL but with a different number on the end: 'redis://localhost:6379/0'




Virtual Env setup (inside the api root directory)
---
    python -m venv ./venv


---


Database Setup 
---
Inside api dir
    source venv/bin/activate   (to set up virtual env if necessary)
    export FLASK_APP=pyfedi.py
    flask db upgrade
    flask init-db


In future if you use git pull and notice some new files in migrations/versions/*, you need to do

    flask db upgrade

---


Run development server
---

    export FLASK_APP=pyfedi.py
    flask run

To enable debug mode and hot reloading, set the environment variable FLASK_ENV=development

    export FLASK_ENV=development
    export FLASK_APP=pyfedi.py
    flask run

Make sure you have activated the venv by running

    source venv/bin/activate
first!


Database Changes
---
create a migration based on recent changes to app/models.py:

    flask db migrate -m "users table"

run migrations

    flask db upgrade

Keeping your local instance up to date
---
In a development environment, all you need to do is

    git pull
    flask db upgrade

In production, celery and flask run as background services so they need to be restarted manually. Run the `./deploy.sh` script
to easily restart services at the same time as pulling down changes from git, etc.

Federation during development
---

Federation doesn't work without SSL, without a domain name or without your server being accessible from outside your network. So, when running on http://127.0.0.1:5000 you have none of those.

The site will still run without federation. You can create local communities and post in them...

My way around this is to use ngrok.com, which is a quick and simple way to create a temporary VPN with a domain and SSL. On the free plan your domain changes every few days, which will break federation. $10 per month will get you https://yourwhatever.ngrok.app which won't change. 

Once you have ngrok working, edit the .env file and change the SERVER_NAME variable to your new domain name. 

Running PieFed in production
---

Copy celery_worker.default.py to celery_worker.py. Edit DATABASE_URL and SERVER_NAME to have the same values as in .env.

Edit gunicorn.conf.py and change worker_tmp_dir if needed.

You will want to [tune PostgreSQL](https://pgtune.leopard.in.ua/). [More on this](https://www.enterprisedb.com/postgres-tutorials/how-tune-postgresql-memory).
If you have more than 4 GB of RAM, consider [turning on 'huge pages'](https://www.percona.com/blog/why-linux-hugepages-are-super-important-for-database-servers-a-case-with-postgresql/)
also [see this](https://pganalyze.com/blog/5mins-postgres-tuning-huge-pages).

(PgBouncer)[https://www.pgbouncer.org] can be helpful in a high traffic situation.

Gunicorn and Celery need to run as background services:

### Gunicorn

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

### Celery

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

### Enable and start background services

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