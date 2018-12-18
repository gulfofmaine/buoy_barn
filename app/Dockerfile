FROM python:3.7.0

# Output logging faster
ENV PYTHONUNBUFFERED 1
# Don't write bytecode
ENV PYTHONDONTWRITEBYTECODE 1

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
RUN pip install -r requirements.txt

# Copy app to working directory
COPY ./* /app/
 