FROM python:3.9-alpine

# create directory for the app user
RUN mkdir -p /home/app

# create the app user
RUN addgroup -S app && adduser -S app -G app

# create the appropriate directories
ENV HOME=/home/app
WORKDIR /home/app

# copy files
COPY ./requirements.txt .
COPY *.py .

# Install requirements
RUN pip3 install -r requirements.txt

# Run
CMD [ "python3", "app.py"]