FROM python:2.7.12-alpine
RUN pip install networkx flask requests
WORKDIR /opt/tnova_connector
COPY . ./
EXPOSE 5000
ENTRYPOINT ["python", "connector.py", "-p", "5000"]
