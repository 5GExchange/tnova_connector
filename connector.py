#!/usr/bin/env python
# Copyright 2016 Janos Czentye
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import argparse
import datetime
import httplib
import json
import logging
import os
import sys
import uuid

import requests
from flask import Flask, Response, request
from requests.exceptions import ConnectionError

from colored_logger import ColoredLogger
from converter import TNOVAConverter
from service_mgr import ServiceManager
from vnf_catalogue import VNFCatalogue, MissingVNFDException

try:
  # Import from ESCAPEv2
  from escape.nffg_lib.nffg import NFFG
except (ImportError, AttributeError):
  try:
    # Import from locally in case of separately distributed version
    from nffg_lib.nffg import NFFG
  except ImportError:
    # At last try to import from original place in escape git repo
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                 "../escape/escape/nffg_lib/")))
    from nffg import NFFG

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

# Other constants
PWD = os.path.realpath(os.path.dirname(__file__))
POST_HEADERS = {"Content-Type": "application/json"}

# Create REST-API handler app
root_logger = logging.getLogger()
root_logger.addHandler(ColoredLogger.createHandler())
root_logger.setLevel(logging.DEBUG)

app = Flask("Connector")
# create Catalogue for VNFDs
catalogue = VNFCatalogue(remote_store=USE_VNF_STORE,
                         url=os.path.join(CATALOGUE_URL, CATALOGUE_PREFIX),
                         catalogue_dir=CATALOGUE_DIR,
                         logger=app.logger)
# Create converter
converter = TNOVAConverter(vnf_catalogue=catalogue,
                           logger=app.logger)
# Create Service manager
service_mgr = ServiceManager(service_dir=os.path.join(PWD, SERVICE_NFFG_DIR),
                             escape_url=ESCAPE_URL,
                             logger=app.logger)


def convert_service (nsd_file):
  """
  Perform the conversion of the received NSD and save the NFFG.

  :param nsd_file: path of the stored NSD file
  :type nsd_file: str
  :return: conversion was successful or not
  :rtype: bool
  """
  app.logger.info("Start converting received NSD...")
  # Convert the NSD given by file name
  sg = converter.convert(nsd_file=nsd_file)
  app.logger.info("NSD conversion has been ended!")
  if sg is None:
    app.logger.error("Service conversion was failed! Service is not saved!")
    return False
  # Save result NFFG into a file
  sg_path = os.path.join(PWD, SERVICE_NFFG_DIR, "%s.nffg" % sg.id)
  with open(sg_path, 'w') as f:
    f.write(sg.dump())
  app.logger.info("Converted NFFG has been saved! Path: %s" % sg_path)
  return True


@app.route("/nsd", methods=['POST'])
def add_nsd ():
  """
  REST-API function for NSD conversion and storing.

  Rule: /nsd
  Method: POST
  Body: NSD in JSON

  :return: HTTP Response
  :rtype: :any:`flask.Response`
  """
  app.logger.info("Call add_nsd() with path: POST /nsd")
  try:
    # Parse data as JSON
    data = json.loads(request.data)
    filename = data['nsd']['id']
    path = os.path.join(PWD, NSD_DIR, "%s.json" % filename)
    with open(path, 'w') as f:
      f.write(json.dumps(data, indent=2, sort_keys=True))
    app.logger.info("Received NSD has been saved: %s!" % path)
    # Initiate service conversion in a thread
    # t = Thread(target=convert_service, name="SERVICE_CONVERTER", args=(path,))
    # t.start()
    if not convert_service(nsd_file=path):
      return Response(status=httplib.INTERNAL_SERVER_ERROR)
    service_mgr.add_service(service_id=filename)
    # Response with 200 OK
    return Response(status=httplib.ACCEPTED)
  except ValueError:
    app.logger.exception("Received data is not valid JSON!")
    app.logger.debug("Received body:\n%s" % request.data)
    return Response(status=httplib.INTERNAL_SERVER_ERROR)
  except KeyError:
    app.logger.exception("Received data is not valid NSD!")
    app.logger.debug("Received body:\n%s" % request.data)
    return Response(status=httplib.INTERNAL_SERVER_ERROR)
  except MissingVNFDException:
    app.logger.exception("Unrecognisable VNFD has been found in NSD!")
    return Response(status=httplib.INTERNAL_SERVER_ERROR)
  except:
    app.logger.exception(
      "Got unexpected exception during NSD -> NFFG conversion!")
    return Response(status=httplib.INTERNAL_SERVER_ERROR)


@app.route("/vnfd", methods=['POST'])
def add_vnfd ():
  """
  REST-API function for VNFD storing. This function is defined for backward
  compatibility.

  Rule: /vnfd
  Method: POST
  Body: VNFD in JSON

  :return: HTTP Response
  :rtype: :any:`flask.Response`
  """
  app.logger.info("Call add_vnfd() with path: POST /vnfd")
  try:
    data = json.loads(request.data)
    filename = data['id']
    path = os.path.join(PWD, CATALOGUE_DIR, "%s.nffg" % filename)
    with open(path, 'w') as f:
      f.write(json.dumps(data))
    app.logger.info("Received VNFD has been saved: %s!" % path)
    return Response(status=httplib.ACCEPTED)
  except ValueError:
    app.logger.error("Received data is not valid JSON!")
    app.logger.debug("Received body:\n%s" % request.data)
    return Response(status=httplib.INTERNAL_SERVER_ERROR)
  except KeyError:
    app.logger.error("Received data is not valid VNFD!")
    app.logger.debug("Received body:\n%s" % request.data)
    return Response(status=httplib.INTERNAL_SERVER_ERROR)


@app.route("/service", methods=['POST'])
def initiate_service ():
  """
  REST-API function for service initiation. The request contains the
  previously defined and converted NSD id. The stored NFFG will be send to
  ESCAPE's REST-API.

  Rule: /service
  Method: POST
  Body: service request id in JSON object with key: "ns-id"

  :return: HTTP Response
  :rtype: :any:`flask.Response`
  """
  app.logger.info("Call initiate_service() with path: POST /service")
  try:
    params = json.loads(request.data)
    if "ns_id" not in params:
      app.logger.error("Missing NSD id from service initiation request!")
      app.logger.debug("Received body:\n%s" % request.data)
      return Response(status=httplib.NOT_FOUND)
    sg_id = params['ns_id']
    app.logger.info("Received service initiation with id: %s" % sg_id)
  except ValueError:
    app.logger.error("Received POST params are not valid JSON!")
    app.logger.debug("Received body:\n%s" % request.data)
    return Response(status=httplib.UNSUPPORTED_MEDIA_TYPE)
  sg_path = os.path.join(PWD, SERVICE_NFFG_DIR, "%s.nffg" % sg_id)
  with open(sg_path) as f:
    sg = json.load(f)
  esc_url = os.path.join(ESCAPE_URL, ESCAPE_PREFIX)
  try:
    ret = requests.post(url=esc_url,
                        headers=POST_HEADERS,
                        json=sg)
    app.logger.info(
      "Service initiation has been forwarded with result: %s" % ret.status_code)
    service_mgr.set_service_status(service_id=sg_id,
                                   status=ServiceManager.STATUS_RUNNING)
    return Response(status=httplib.ACCEPTED)
  except ConnectionError:
    app.logger.error("ESCAPE is not available!")
    return Response(status=httplib.INTERNAL_SERVER_ERROR)
  except:
    app.logger.exception("Got unexpected exception during service initiation!")
    return Response(status=httplib.BAD_REQUEST)


@app.route("/ns-instances", methods=['GET'])
def list_service ():
  """
  REST-API function for service listing.

  Rule: /ns-instances
  Method: GET
  Body: None

  Sample response:
  [
    {
      "id":"456",
      "name":"name of the ns",
      "status":"stopped
    }
  ]

  :return: HTTP Response
  :rtype: :any:`flask.Response`
  """
  app.logger.info("Call list_service() with path: GET /ns-instances")
  services = service_mgr.get_running_services()
  resp = [{"id": s.id, "name": s.name, "status": "running"} for s in services]
  return Response(status=httplib.OK,
                  content_type="application/json",
                  response=json.dumps(resp))


@app.route("/ns-instances/<service_id>", methods=['PUT'])
def update_service (service_id):
  """
  REST-API function for service deletion. The request URL contains the
  previously initiated NSD id. The stored NFFG will be send to
  ESCAPE's REST-API.

  Rule: /ns-instances/{id}
  Method: PUT
  Body: required service status
  {
    "status": "stopped"
  }

  Sample response: 200 OK
  {
     "id":"456",
     "ns-id":"987",
     "status":"stopped",
     "created_at":"2014-11-21T14:18:09Z",
     "updated_at":"2014-11-25T10:01:52Z"
  }

  :param service_id: service ID
  :type service_id: str
  :return: HTTP Response 200 OK
  :rtype: :any:`flask.Response`
  """
  app.logger.info("Call update_service() with path: PUT /ns-instances/<id>")
  app.logger.debug("Detected service id: %s" % service_id)
  if request.data is None:
    return Response(status=httplib.NO_CONTENT)
  try:
    params = json.loads(request.data)
    if "status" not in params:
      app.logger.error("Missing NSD id from service request!")
      app.logger.debug("Received body:\n%s" % request.data)
      return Response(status=httplib.NOT_FOUND)
    status = params['status']
  except ValueError:
    app.logger.error("Received POST params are not valid JSON!")
    app.logger.debug("Received body:\n%s" % request.data)
    return Response(status=httplib.UNSUPPORTED_MEDIA_TYPE)
  if status != 'stopped':
    app.logger.error("Service status request: %s is not supported yet!" %
                     status)
    return Response(status=httplib.NOT_IMPLEMENTED)
  app.logger.info("Received service deletion with id: %s" % service_id)
  # Load NFFG from file
  sg_path = os.path.join(PWD, SERVICE_NFFG_DIR, "%s.nffg" % service_id)
  sg = NFFG.parse_from_file(path=sg_path)
  # Set DELETE mode
  sg.mode = NFFG.MODE_DEL
  esc_url = os.path.join(ESCAPE_URL, ESCAPE_PREFIX)
  try:
    ret = requests.put(url=esc_url,
                       headers=POST_HEADERS,
                       json=sg)
    app.logger.info("Service deletion has been forwarded with result: %s" %
                    ret.status_code)
    service_mgr.set_service_status(service_id=service_id,
                                   status=ServiceManager.STATUS_STOPPED)
  except ConnectionError:
    app.logger.error("ESCAPE is not available!")
    return Response(status=httplib.INTERNAL_SERVER_ERROR)
  except:
    app.logger.exception("Got unexpected exception during service initiation!")
    return Response(status=httplib.BAD_REQUEST)
  # Create and send Response
  resp = {"id": uuid.uuid1(),
          "ns-id": sg.id,
          "status": "stopped",
          "created_at": datetime.datetime.fromtimestamp(
            os.path.getctime(sg_path)).isoformat(),
          "updated_at": datetime.datetime.now().isoformat()}
  return Response(status=httplib.OK,
                  content_type="application/json",
                  response=json.dumps(resp))


if __name__ == "__main__":
  parser = argparse.ArgumentParser(
    description="TNOVAConnector: Middleware component which make the "
                "connection between Marketplace and ESCAPE with automatic "
                "request conversion",
    add_help=True)
  parser.add_argument("-p", "--port", action="store", default=5000,
                      type=int, help="REST-API port (default: 5000)")
  parser.add_argument("-d", "--debug", action="store_true", default=False,
                      help="run in debug mode (default logging level: INFO)")
  args = parser.parse_args()
  # logging.setLoggerClass(ColoredLogger)
  # logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
  level = logging.DEBUG if args.debug else logging.INFO
  # app.logger.addHandler(ColoredLogger.createHandler())
  app.logger.handlers[:] = [ColoredLogger.createHandler()]
  app.logger.setLevel(level)
  app.logger.propagate = False
  app.logger.info("Set logging level: %s",
                  logging.getLevelName(app.logger.getEffectiveLevel()))
  app.run(host='0.0.0.0', port=args.port, debug=args.debug, use_reloader=False)
