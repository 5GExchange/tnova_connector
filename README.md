# TNOVAConverter: Converting Network Services from T-NOVA: NSD and VNFD files into UNIFY: NFFG

## Introduction

TNOVAConverter is a middleware component which is responsible for creating the connection 
between Marketplace and ESCAPE and enables service initiations from T-NOVA GUI into UNIFY's 
resource domain.

## Installation

Connector module is implemented entirely in Python.

## Requirements

* Python 2.7.6+
* NFFG 1.0

### Dependencies

```bash
sudo apt install python python-pip
sudo -H pip install flask requests networkx
```

To clone the repository use the following command:

```bash
git clone git@5gexgit.tmit.bme.hu:unify/tnova_connector.git
```

If you want to use as a submodule e.g. from ESCAPE repository use the following command to get the latest code:

```bash
git submodule update
```

or

```bash
git pull -v --recurse-submodules
```
If the NFFG submodule is not initialized, use the following command:

```bash
git submodule update --init
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

Connector tries to acquire the URLs in the following order:

1. Command line argument (-e; -v)
2. Environment variable (use the name of the constants in the connector script: `ESCAPE_URL` and `VNF_STORE_URL`)
3. Default value defined in the top of the script

## Usage

```
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

The RESPT-API calls use no prefix in path by default and follow the syntax: ``http://<ip>:<port|5000>/<operation>``

| Operation                     | Params                            | HTTP verb | Description                                                                                        |
|:-----------------------------:|:----------------------------------|:---------:|:---------------------------------------------------------------------------------------------------|
| /nsd                          | NSD desc. in JSON                 | POST      | Send an NSD to the connector, convert to NFFG using local VNFDs or a remote VNF Store and store it |
| /vnfd                         | VNFD desc. in JSON                | POST      | Send a VNFD to the connector and store it locally (for backward compatibility and testing purposes)|
| /service                      | NSD id in JSON with key: "ns_id"  | POST      | Initiate a pre-defined NSD with the NSD id by sending the converted NFFG to ESCAPE                 |
| /ns-instances                 | None                              | GET       | List services                                                                                      |
| /ns-instances/{id}            | Service status JSON               | PUT       | Set service status - Not supported yet                                                             |
| /ns-instances/{id}/terminate  | None                              | PUT       | Delete a defined service given by {id}                                                             |

## TNOVAConverter as a Docker container

TNOVAConverter can be run in a Docker container. To create the basic image, issue the following command 
in the project root:

```bash
$ docker build --rm --no-cache -t tnova_connector .
```

This command creates a minimal image based on the alpine Python image with the name: _tnova_connector_, 
installs the required Python dependencies listed in `requirement.txt` and sets the entry point.

To create and start a persistent container based on the _tnova_connector_ image, use the following commands:

```bash
$ docker run --name connector -p 5000:5000 -it tnova_connector
$ docker start -i connector
```

To create a one-time container, use the following command:

```bash
$ docker run --rm -p 5000:5000 -ti tnova_connector
```

## License

Licensed under the Apache License, Version 2.0; see LICENSE file.

    Copyright (C) 2017 by
    János Czentye <janos.czentye@tmit.bme.hu>