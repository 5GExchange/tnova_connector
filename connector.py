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
import json
import os

from flask import Flask, request, abort

app = Flask("T-NOVA_Connector")


@app.route("/nsd", methods=['POST'])
def nsd ():
  try:
    data = json.loads(request.data)
    filename = data['nsd']['id']
    dirname = os.path.realpath(os.path.dirname(__file__))
    path = "%s/nsds/%s.json" % (dirname, filename)
    with open(path, 'w') as f:
      f.write(str(data))
    app.logger.info("Received NSD has been saved: %s!" % path)
    return "OK"
  except ValueError:
    app.logger.error("Received data is not valid JSON!")
    abort(500)
  except KeyError:
    app.logger.error("Received data is not a valid NSD!")
    abort(500)


@app.route("/vnfd", methods=['POST'])
def vnfd ():
  try:
    data = json.loads(request.data)
    filename = data['id']
    dirname = os.path.realpath(os.path.dirname(__file__))
    path = "%s/vnf_catalogue/%s.json" % (dirname, filename)
    with open(path, 'w') as f:
      f.write(str(data))
    app.logger.info("Received VNFD has been saved: %s!" % path)
    return "OK"
  except ValueError:
    app.logger.error("Received data is not valid JSON!")
    abort(500)
  except KeyError:
    app.logger.error("Received data is not a valid VNFD!")
    abort(500)


if __name__ == "__main__":
  app.run(debug=True, port=5000)
