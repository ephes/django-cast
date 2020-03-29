# to start the example don't forget to set the envs
Set-Item "env:DJANGO_SETTINGS_MODULE" example_site.settings.dev
python manage.py runserver localhost:8000
