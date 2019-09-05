FROM python:3.7.4@sha256:a81fcda6626c85c77382b4a8b73e674d20a9764bf7407a005d800ceb79ee3684

# Output logging faster
ENV PYTHONUNBUFFERED 1
# Don't write bytecode
ENV PYTHONDONTWRITEBYTECODE 1
# Show deprication warnings https://docs.djangoproject.com/en/2.2/howto/upgrade-version/#resolving-deprecation-warnings
ENV PYTHONWARNINGS always

# geodjango spatial requirements
RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils=2.31.1-16 \
    libproj-dev=5.2.0-1 \
    gdal-bin=2.4.0+dfsg-1+b1 \
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