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
import httplib
import json
import logging
import os

import requests
from flask import Flask, Response, request, abort
from requests.exceptions import ConnectionError

from converter import TNOVAConverter, VNFCatalogue, MissingVNFDException

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
app = Flask("T-NOVA_Connector")
# create Catalogue for VNFDs
catalogue = VNFCatalogue(remote_store=USE_VNF_STORE,
                         url=os.path.join(CATALOGUE_URL, CATALOGUE_PREFIX),
                         catalogue_dir=CATALOGUE_DIR, logger=app.logger)
# Create converter
converter = TNOVAConverter(vnf_catalogue=catalogue, logger=app.logger)


def convert_service (nsd_file):
  """
  Perform the conversion of the received NSD and save the NFFG.

  :param nsd_file: path of the stored NSD file
  :type nsd_file: str
  :return: None
  """
  app.logger.info("Start converting received NSD...")
  # Convert the NSD given by file name
  sg = converter.convert(nsd_file=nsd_file)
  app.logger.info("NSD conversion has been ended!")
  if sg is None:
    app.logger.error("Service conversion was failed! Service is not saved!")
    return
  # Save result NFFG into a file
  sg_path = os.path.join(PWD, SERVICE_NFFG_DIR, "%s.nffg" % sg.id)
  with open(sg_path, 'w') as f:
    f.write(sg.dump())
  app.logger.info("Converted NFFG has been saved! Path: %s" % sg_path)


@app.route("/nsd", methods=['POST'])
def nsd ():
  """
  REST-API function for NSD conversion and storing.

  Rule: /nsd
  Method: POST
  Body: NSD in JSON

  :return: HTTP Response
  :rtype: :any:`flask.Response`
  """
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
    convert_service(nsd_file=path)
    # Response with 200 OK
    return Response(status=httplib.ACCEPTED)
  except ValueError:
    app.logger.exception("Received data is not valid JSON!")
    abort(500)
  except KeyError:
    app.logger.exception("Received data is not valid NSD!")
    abort(500)
  except MissingVNFDException:
    app.logger.exception("Unrecognisable VNFD is in NSD!")
    abort(500)
  except:
    app.logger.exception(
      "Got unexpected exception during NSD -> NFFG conversion!")
    abort(500)


@app.route("/vnfd", methods=['POST'])
def vnfd ():
  """
  REST-API function for VNFD storing. This function is defined for backward
  compatibility.

  Rule: /vnfd
  Method: POST
  Body: VNFD in JSON

  :return: HTTP Response
  :rtype: :any:`flask.Response`
  """
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
    abort(500)
  except KeyError:
    app.logger.error("Received data is not valid VNFD!")
    abort(500)


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
  try:
    params = json.loads(request.data)
    if "ns-id" not in params:
      app.logger.error("Missing NSD id from service initiation request!")
      abort(404)
    sg_id = params['ns-id']
    app.logger.info("Received service initiation with id: %s" % sg_id)
  except ValueError:
    app.logger.error("Received POST params are not valid JSON!")
    abort(415)
  sg_path = os.path.join(PWD, SERVICE_NFFG_DIR, "%s.nffg" % sg_id)
  with open(sg_path) as f:
    sg = json.load(f)
  esc_url = os.path.join(ESCAPE_URL, ESCAPE_PREFIX)
  try:
    ret = requests.post(url=esc_url, headers=POST_HEADERS, json=sg)
    app.logger.info(
      "Service initiation has been forwarded with result: %s" % ret.status_code)
    return Response(status=httplib.ACCEPTED)
  except ConnectionError:
    app.logger.error("ESCAPE is not available!")
    abort(500)
  except:
    app.logger.exception("Got unexpected exception during service initiation!")
    abort(400)


if __name__ == "__main__":
  parser = argparse.ArgumentParser(
    description="TNOVAConnector: Middleware component which make the "
                "connection between Marketplace and ESCAPE with automatic "
                "request conversion",
    add_help=True)
  parser.add_argument("-p", "--port", action="store", default=5000,
                      type=int, help="REST-API port (default: 5000)")
  parser.add_argument("-d", "--debug", action="store_true", default=False,
                      help="run in debug mode")
  args = parser.parse_args()
  logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
  app.logger.info("Logging level: %s",
                  logging.getLevelName(app.logger.getEffectiveLevel()))
  app.run(port=args.port, debug=args.debug, use_reloader=False)
