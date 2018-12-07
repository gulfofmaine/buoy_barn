FROM python:3.7.0

# Output logging faster
ENV PYTHONUNBUFFERED 1
# Don't write bytecode
ENV PYTHONDONTWRITEBYTECODE 1

# geodjango spatial requirements
RUN apt-get update && apt-get install -y \
    binutils \
    libproj-dev \
    gdal-bin

# Working directory
RUN mkdir /app
WORKDIR /app

# Install requirements
ADD ./requirements.txt /app/
RUN pip install -r requirements.txt

# Copy app to working directory
ADD ./* /app/
 