# TNOVAConverter: Converting Network Services from T-NOVA: NSD and VNFD files into UNIFY: NFFG

## Introduction

TNOVAConverter is a middleware component which is responsible for creating the connection 
between Marketplace and ESCAPE and enables service initiations from T-NOVA GUI into UNIFY's 
resource domain.

## Installation

Connector module is implemented entirely in Python.

### Dependencies

```bash
sudo apt install python-pip
sudo -H pip install flask requests 
```

To clone the repository use the following command:

```bash
git clone git@5gexgit.tmit.bme.hu:unify/tnova_connector.git
```

If you want to use as a submodule e.g. from ESCAPE repository use the following command to get the latest code:

```bash
git submodule update --remote --merge
```

or

```bash
git pull -v --recurse-submodules
```

## Configuration

For simplicity every configuration parameter can be set as a global constant in the `connector.py` module:

```python
### Connector configuration parameters
CATALOGUE_URL = "http://172.16.178.128:8080"  # VNF Store URL as <host>:<port>
CATALOGUE_PREFIX = "NFS/vnfds"  # static prefix used in REST calls
USE_VNF_STORE = True  # enable dynamic VNFD acquiring from VNF Store
CATALOGUE_DIR = "vnf_catalogue"  # read VNFDs from dir if VNF Store is disabled
ESCAPE_URL = "http://localhost:8008"  # ESCAPE's top level REST-API
ESCAPE_PREFIX = "escape/sg"  # static prefix for service request calls
NSD_DIR = "nsds"  # dir name used for storing received NSD files
SERVICE_NFFG_DIR = "services"  # dir name used for storing converted services
### Connector configuration parameters
```

## Usage

```bash
$ ./connector.py -h
usage: connector.py [-h] [-p PORT] [-d]

TNOVAConnector: Middleware component which make the connection between
Marketplace and ESCAPE with automatic request conversion

optional arguments:
  -h, --help            show this help message and exit
  -p PORT, --port PORT  REST-API port (default: 5000)
  -d, --debug           run in debug mode (default logging level: INFO)
```

## REST-API

| Path | Params | HTTP verb | Description |
|---|
| /nsd | NSD desc. in JSON | POST | Send an NSD to the connector, convert to NFFG using local VNFDs or a remote VNF Store and store it |
| /vnfd  | VNFD desc. in JSON| POST | Send a VNFD to the connector and store it locally |
| /service | NSD id  in JSON with key: "ns-id" | POST | Initiate a pre-defined NSD with the NSD id by sending the converted NFFG to ESCAPE |
