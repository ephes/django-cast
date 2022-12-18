# Bootstrap Django-Cast

## Generate Hashes

Development:
```shell
python -m piptools compile --upgrade --allow-unsafe --generate-hashes requirements/production.in requirements/develop.in --output-file requirements/develop.txt
```

Production:

```shell
python -m piptools compile --upgrade --allow-unsafe --generate-hashes requirements/production.in --output-file requirements/production.txt
```

## Install Requirements

```shell
python -m piptools sync requirements/develop.txt
```

## Install Cast Package
```shell
python -m pip install -e .
```

## Get Example app running

```shell
python manage.py migrate
```

```shell
python manage.py runserver 0.0.0.0:8000
```
