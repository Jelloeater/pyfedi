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

Federation during development
---

Federation doesn't work without SSL, without a domain name or without your server being accessible from outside your network. So, when running on http://127.0.0.1:5000 you have none of those.

The site will still run without federation. You can create local communities and post in them...

My way around this is to use ngrok.com, which is a quick and simple way to create a temporary VPN with a domain and SSL. On the free plan your domain changes often, which will break federation every time you reconnect. $10 per month will get you https://yourwhatever.ngrok.app which won't change. 

Once you have ngrok working, edit the .env file and change the SERVER_NAME variable to your new domain name. 


