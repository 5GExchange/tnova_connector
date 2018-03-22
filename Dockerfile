################################################################################
# Dockerfile to build the TNOVA connector image
################################################################################
FROM python:2.7.14-alpine
MAINTAINER Janos Czentye <czentye@tmit.bme.hu>
ARG GIT_REVISION=unknown
LABEL git-revision=$GIT_REVISION    
LABEL Description="TNOVA-Connector" Project="5GEx" version="1.0.0+"
WORKDIR /opt/tnova_connector
ENV PYTHONUNBUFFERED=1 LANG=C.UTF-8
COPY . ./
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 5000 9000
STOPSIGNAL SIGINT
ENTRYPOINT ["python", "connector.py"]
CMD ["--debug", "--port", "5000", "--virtualizer", "--callback"]