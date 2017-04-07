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

If the NFFG submodule is not initialized, use the following command:

```bash
git submodule update --init
```

## Configuration

For simplicity every configuration parameter can be set as a global constant in the `connector.py` module:

```python
# Connector configuration parameters
RO_URL = "http://localhost:8008/escape/sg"  # ESCAPE's top level REST-API
VNF_STORE_URL = "http://localhost:8080/NFS/vnfds"

USE_VNF_STORE = False  # enable dynamic VNFD acquiring from VNF Store
NSD_DIR = "nsds"  # dir name used for storing received NSD files
SERVICE_NFFG_DIR = "services"  # dir name used for storing converted services
CATALOGUE_DIR = "vnf_catalogue"  # read VNFDs from dir if VNF Store is disabled

# Communication related parameters
USE_CALLBACK = False
CALLBACK_URL = None
USE_VIRTUALIZER_FORMAT = False
```

Connector tries to acquire the URLs in the following order:

1. Command line argument (-e; -v)
2. Environment variable (use the name of the constants in the connector script: `ESCAPE_URL`, `CALLBACK_URL` and `VNF_STORE_URL`)
3. Default value defined in the top of the script

## Usage

```
$ ./connector.py -h
usage: connector.py [-h] [-d] [-c [URL]] [-m URL] [-r URL] [-p PORT]
                    [-t TIMEOUT] [-v VNFS]

TNOVAConnector: Middleware component which make the connection between
Marketplace and RO with automatic request conversion

optional arguments:
  -h, --help            show this help message and exit
  -d, --debug           run in debug mode (can use multiple times for more
                        verbose logging, default logging level: INFO)
  -c [URL], --callback [URL]
                        enables callbacks from the RO with given URL, default:
                        http://localhost:9000/callback
  -m URL, --monitoring URL
                        URL of the monitoring component, default: None
  -r URL, --ro URL      RO's full URL, default:
                        http://localhost:8008/escape/sg
  -p PORT, --port PORT  REST-API port (default: 5000)
  -t TIMEOUT, --timeout TIMEOUT
                        timeout in sec for HTTP communication, default: 5s
  -v VNFS, --vnfs VNFS  enables remote VNFStore with given full URL, default:
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
| /ns-instances/{id}/terminate  | None                              | PUT       | Delete a defined service given by {id}                                                             |

## TNOVAConverter as a Docker container

TNOVAConverter can be run in a Docker container. To create the basic image, issue the following command 
in the project root:

```bash
$ sudo docker build --rm --no-cache -t mdo/tnova_connector .
```

This command creates a minimal image based on the alpine Python image with the name: _tnova_connector_, 
installs the required Python dependencies listed in `requirement.txt` and sets the entry point.

To create and start a persistent container based on the _tnova_connector_ image, use the following commands:

```bash
$ sudo docker run --name connector -p 5000:5000 -p 9000:9000 -it mdo/tnova_connector
$ sudo docker start -i connector
```

To create a one-time container, use the following command:

```bash
$ sudo docker run --rm -p 5000:5000 -p 9000:9000 -ti mdo/tnova_connector
```

# Testing

The project contains a docker-compose config file to test the cooperation of 
tnova_connector and the Resource Orchestrator aka ESCAPE.

The config file requires pre-built Docker images with specific names:
  * `tnova_connector` for the connector (partial NSO functions)
  * `mdo/ro` for ESCAPE (RO)
  * `dummy` for the dummy orchestrator (dataplane emulation)
  
These images can be built by the following commands:

```bash
# Build connector image
tnova_connector$ sudo docker build --rm --no-cache -t mdo/tnova_connector .
# Build ESCAPE image
escape$ sudo docker build --rm --no-cache -t mdo/ro .
# Build Dummy Orchestrator image
dummy$ sudo docker build --no-cache --rm -t dummy .

# Created images
$ sudo docker images
REPOSITORY            TAG                 IMAGE ID            CREATED             SIZE
dummy                 latest              1fddbe0c5647        19 hours ago        88.3 MB
mdo/ro                latest              1148ca557fa5        19 hours ago        854 MB
mdo/tnova_connector   latest              d26bf0c69424        19 hours ago        95.7 MB
python                2.7.13-alpine       b63d02d8829b        4 weeks ago         71.5 MB
python                2.7.13              b4b107fcc777        8 weeks ago         679 MB
```

To start the test setup use one of the following commands:

```bash
$ sudo docker-compose up
# Run in background
$ sudo docker-compose up -d
$ sudo docker-compose logs -f {escape|tnovaconnector|dummy}
```

To test the latest code the additional "debug" docker-compose file need to be 
given. This additional config file attach the project folders into the containers.
The locations of the project's code are extracted from environment variables.
The following variables must be predefined:

```bash
export ESCAPEHOME=...
export DUMMYHOME=...
export TNOVACONNECTORHOME=...
```

To run the setup in "debug" mode use the following command:

```bash
$ sudo docker-compose -f docker-compose.yml -f docker-compose.debug.yml up
```

## License

Licensed under the Apache License, Version 2.0; see LICENSE file.

    Copyright (C) 2017 by
    János Czentye <janos.czentye@tmit.bme.hu>