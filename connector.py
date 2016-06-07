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
import httplib
import json
import logging
import os

import requests
from flask import Flask, Response, request, abort

from converter import TNOVAConverter, VNFCatalogue

# Configuration parameters
CATALOGUE_DIR = "vnf_catalogue"
USE_VNF_STORE = True
CATALOGUE_URL = "http://172.16.178.128:8080"
CATALOGUE_PREFIX = "NFS/vnfds"
ESCAPE_URL = "http://localhost:8008"
ESCAPE_PREFIX = "escape/sg"
NSD_DIR = "nsds"
SERVICE_NFFG_DIR = "services"

# Other constants
PWD = os.path.realpath(os.path.dirname(__file__))
POST_HEADERS = {"Content-Type": "application/json"}

# Create REST-API handler app
app = Flask("T-NOVA_Connector")
# create Catalogue for VNFDs
catalogue = VNFCatalogue(remote_store=USE_VNF_STORE, url=CATALOGUE_URL,
                         catalogue_dir=CATALOGUE_DIR, logger=app.logger)
# Create converter
converter = TNOVAConverter(vnf_catalogue=catalogue, logger=app.logger)


def convert_service (nsd_file):
  # Convert the NSD given by file name
  sg = converter.convert(nsd_file=nsd_file)
  if sg is None:
    app.logger.error("Service conversion was failed! Service is not saved!")
    return
  # Save result NFFG into a file
  sg_path = os.path.join(PWD, SERVICE_NFFG_DIR, "%s.json" % sg.id)
  with open(sg_path, 'w') as f:
    f.write(sg.dump())


@app.route("/nsd", methods=['POST'])
def nsd ():
  try:
    # Parse data as JSON
    data = json.loads(request.data)
    filename = data['nsd']['id']
    path = os.path.join(PWD, NSD_DIR, "%s.json" % filename)
    with open(path, 'w') as f:
      f.write(json.dumps(data))
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


@app.route("/vnfd", methods=['POST'])
def vnfd ():
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


@app.route("/service/<sg_id>", methods=['POST'])
def initiate_service (sg_id):
  app.logger.info("Received service initiation with id: %s" % sg_id)
  sg_path = os.path.join(PWD, SERVICE_NFFG_DIR, "%s.nffg" % sg_id)
  with open(sg_path) as f:
    sg = json.load(f)
  esc_url = os.path.join(ESCAPE_URL, ESCAPE_PREFIX)
  ret = requests.post(url=esc_url, headers=POST_HEADERS, json=sg)
  app.logger.info(
    "Service initiation has been forwarded with result: %s" % ret.status_code)


if __name__ == "__main__":
  # app.run(debug=True, port=5000)
  logging.basicConfig(level=logging.DEBUG)
  app.run(port=5000)
