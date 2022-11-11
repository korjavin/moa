FROM debian:testing
RUN apt update && apt install -y python3 python3-dev build-essential
RUN apt install -y python3-pip
RUN apt install -y git
ADD . /app
WORKDIR /app
RUN pip3 install -r requirements.txt
