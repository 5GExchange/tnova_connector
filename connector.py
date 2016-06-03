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

from converter import TNOVAConverter

PWD = os.path.realpath(os.path.dirname(__file__))
CATALOGUE_DIR = "vnf_catalogue"
NSD_DIR = "nsds"
SERVICE_NFFG_DIR = "sg"
ESCAPE_URL = "http://localhost:8008/escape/sg"

app = Flask("T-NOVA_Connector")


def convert_service (nsd_file):
  # Create converter
  converter = TNOVAConverter(logger=app.logger, catalogue_dir=CATALOGUE_DIR)
  # Convert the NSD given by file name
  sg = converter.convert(nsd_file=nsd_file)
  if sg is None:
    app.logger.error("Service conversion was failed!")
    return
  # Save result NFFG into a file
  sg_path = nsd_file.replace(NSD_DIR, SERVICE_NFFG_DIR)
  with open(sg_path, 'w') as f:
    f.write(sg.dump())


@app.route("/nsd", methods=['POST'])
def nsd ():
  try:
    # Parse data as JSON
    data = json.loads(request.data)
    filename = data['nsd']['id']
    path = "%s/%s/%s.json" % (PWD, NSD_DIR, filename)
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
    app.logger.exception("Received data is not a valid NSD!")
    abort(500)


@app.route("/vnfd", methods=['POST'])
def vnfd ():
  try:
    data = json.loads(request.data)
    filename = data['id']
    path = "%s/%s/%s.json" % (PWD, CATALOGUE_DIR, filename)
    with open(path, 'w') as f:
      f.write(json.dumps(data))
    app.logger.info("Received VNFD has been saved: %s!" % path)
    return Response(status=httplib.ACCEPTED)
  except ValueError:
    app.logger.error("Received data is not valid JSON!")
    abort(500)
  except KeyError:
    app.logger.error("Received data is not a valid VNFD!")
    abort(500)


@app.route("/service/<sg_id>", methods=['POST'])
def initiate_service (sg_id):
  app.logger.info("Received service initiation with id: %s" % sg_id)
  sg_path = "%s/%s/%s.json" % (PWD, SERVICE_NFFG_DIR, sg_id)
  with open(sg_path) as f:
    sg = json.load(f)
  ret = requests.post(url=ESCAPE_URL, json=sg)
  app.logger.info(
    "Service initiation has benn forwarded with result: %s" % ret.status_code)


if __name__ == "__main__":
  # app.run(debug=True, port=5000)
  logging.basicConfig(level=logging.DEBUG)
  app.run(port=5000)
