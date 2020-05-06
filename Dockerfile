FROM python:3.8-alpine

ADD deploy-heroku.py requirements.txt /opt/

RUN set -ex \
    && apk add --update --no-cache git \
    && pip install -r /opt/requirements.txt \
    && rm -r /root/.cache \
    && rm /opt/requirements.txt

ENTRYPOINT ["/opt/deploy-heroku.py"]
CMD ["deploy"]

