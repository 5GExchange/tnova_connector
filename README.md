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
sudo -H pip install flask requests networkx
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
ESCAPE_URL = "http://localhost:8008/escape/sg"  # ESCAPE's top level REST-API
VNF_STORE_URL = "http://localhost:8080/NFS/vnfds"

USE_VNF_STORE = True  # enable dynamic VNFD acquiring from VNF Store
NSD_DIR = "nsds"  # dir name used for storing received NSD files
SERVICE_NFFG_DIR = "services"  # dir name used for storing converted services
CATALOGUE_DIR = "vnf_catalogue"  # read VNFDs from dir if VNF Store is disabled
```

Connector tries to acquire the URL in the following order:

1. Command line argument (-e; -v)
2. Environment variable (use the name of the constants in the connector script)
3. Default value defined in the top of the script



## Usage

```bash
$ ./connector.py -h
usage: connector.py [-h] [-p PORT] [-d] [-e ESC] [-v VNFS]

TNOVAConnector: Middleware component which make the connection between
Marketplace and ESCAPE with automatic request conversion

optional arguments:
  -h, --help            show this help message and exit
  -p PORT, --port PORT  REST-API port (default: 5000)
  -d, --debug           run in debug mode (can use multiple times for more
                        verbose logging, default logging level: INFO)
  -e ESC, --esc ESC     ESCAPE full URL, default:
                        http://localhost:8008/escape/sg
  -v VNFS, --vnfs VNFS  Enables remote VNFStore with given full URL, default:
                        http://localhost:8080/NFS/vnfds
```

## REST-API

| Path                          | Params                            | HTTP verb | Description                                                                                        |
|:-----------------------------:|:----------------------------------|:---------:|:---------------------------------------------------------------------------------------------------|
| /nsd                          | NSD desc. in JSON                 | POST      | Send an NSD to the connector, convert to NFFG using local VNFDs or a remote VNF Store and store it |
| /vnfd                         | VNFD desc. in JSON                | POST      | Send a VNFD to the connector and store it locally                                                  |
| /service                      | NSD id in JSON with key: "ns_id"  | POST      | Initiate a pre-defined NSD with the NSD id by sending the converted NFFG to ESCAPE                 |
| /ns-instances                 | None                              | GET       | List services                                                                                      |
| /ns-instances/{id}            | Service status JSON               | PUT       | Set service status - Not supported yet                                                             |
| /ns-instances/{id}/terminate  | None                              | PUT       | Delete a defined service given by {id}                                                             |
