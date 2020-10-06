Locally / Setting up your development machine to develop on django-cast
========================================================================

Install `pyenv-win` & set the environment variable PYENV then add $env:PYENV\bin and $env:PYENV\shims to PATH
(attention: some poetry commands may not work with pyenv-win and may be broken, Dominik 2020-03-28)

.. code-block:: powershell

    git clone https://github.com/pyenv-win/pyenv-win.git $env:USERPROFILE\.pyenv
    [Environment]::SetEnvironmentVariable("PYENV", "$env:USERPROFILE\.pyenv\pyenv-win", "Machine")
    $path = [Environment]::GetEnvironmentVariable("PATH", "Machine")
    [Environment]::SetEnvironmentVariable("PATH", "$path;$env:PYENV\bin;$env:PYENV\shims", "Machine")


Restart your shell or `refreshenv`.
Install your prefered python(s) (On Windows-64 bit you have to add -amd64)

.. code-block:: powershell

    pyenv install --list  # lists all installable versions
    pyenv install 3.8.1-amd64  # this is the newest version available on 20-02-2020
    pyenv rehash

Install `poetry`

.. code-block:: powershell

    (Invoke-WebRequest -Uri https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py -UseBasicParsing).Content | python


Install gettext https://mlocati.github.io/articles/gettext-iconv-windows.html & ffmpeg (available via chocolatey `choco install ffmpeg`)

cd into the projects dir setup the project with

.. code-block:: powershell

    poetry install

To checkout the wagtail branch & set local django-settings

.. code-block:: powershell

    git checkout feature/wagtail2
    Set-Item "env:DJANGO_SETTINGS_MODULE" example_site.settings.dev

activate your venv: e.g: `poetry shell` & start the server

.. code-block:: powershell

    python manage.py migrate
    python manage.py createsuperuser
    python manage.py runserver localhost:8000


To run the tests:

.. code-block:: powershell

    # python .\runtests.py tests
    poetry run test

    # coverage run --source cast --branch runtests.py tests
    # coverage report -m
    # coverage html
    poetry run show_coverage

    poetry run docs

    poetry run autoformat

    # linting with flake8
    poetry run lint
