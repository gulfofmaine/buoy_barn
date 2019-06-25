FROM python:3.7.3@sha256:9e0b4f32487ca1863b45383420b8db77990debae748e2e875d2f86fa9510d4a5

# Output logging faster
ENV PYTHONUNBUFFERED 1
# Don't write bytecode
ENV PYTHONDONTWRITEBYTECODE 1
# Show deprication warnings https://docs.djangoproject.com/en/2.2/howto/upgrade-version/#resolving-deprecation-warnings
ENV PYTHONWARNINGS always

# geodjango spatial requirements
RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils=2.28-5 \
    libproj-dev=4.9.3-1 \
    gdal-bin=2.1.2+dfsg-5 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Working directory
RUN mkdir /app
WORKDIR /app

# Install requirements
COPY ./requirements.txt /app/
RUN pip install -r requirements.txt \
    && groupadd uwsgi && useradd -g uwsgi uwsgi

# Copy app to working directory
COPY ./ /app/

RUN chown -R uwsgi:uwsgi /app

ENTRYPOINT ["/app/utils/entrypoint.sh"]

CMD ["uwsgi", "--http", ":8080", "--wsgi-file", "buoy_barn/wsgi.py", "--master", "--processes", "4", "--threads", "2", "--uid", "uwsgi", "--gid", "uwsgi"]