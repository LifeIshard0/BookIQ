web: DJANGO_SETTINGS_MODULE=bookiq.settings_production gunicorn bookiq.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120
release: DJANGO_SETTINGS_MODULE=bookiq.settings_production python manage.py migrate --no-input
