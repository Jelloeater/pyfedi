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

```sudo apt install python3-psycopg2 libpq-dev python3-dev```


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
    sudo apt-get install python3 python3-pip ipython3 libpq-dev python3-psycopg2 python3-dev build-essential
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
add something like this to .env
    
    DATABASE_URL=postgresql+psycopg2://rimu:password@localhost/buddytree

other environment variables include:

    API_KEY - used to control access. Set this to the same on both the frontend and backend
    MAIL_SERVER=email-smtp.us-east-2.amazonaws.com
    MAIL_PORT
    MAIL_USERNAME=
    MAIL_PASSWORD
    MAIL_USE_TLS = False
    MAIL_USE_SSL = False
    EMAIL_FROM
    EMAIL_FROM_NAME=BuddyTree


Virtual Env setup (inside the api root directory)
---
    python -m venv ./venv


---


Database Setup 
---
Inside api dir
    source venv/bin/activate   (to set up virtual env if necessary)
    flask db upgrade
    flask drop-constraint file file_user_id_fkey
    flask init-db
    flask init-intentions
    flask init-interests
    flask init-ages
    flask init-locations
    flask init-roles
    flask init-topics
    flask init-topics2
    flask topic-files
    flask init-activity
    flask init-timezones
    flask init-private-hangout-topics
    flask tidy-private-hangout-topics
    flask init-hosted
    flask init-countries

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
