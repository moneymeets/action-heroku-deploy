FROM python:3.8-alpine

ADD deploy-heroku.py /opt/deploy-heroku.py

RUN set -ex \
    && apk add --update --no-cache git \
    && pip install requests click \
    && rm -r /root/.cache

ENTRYPOINT ["/opt/deploy-heroku.py"]

