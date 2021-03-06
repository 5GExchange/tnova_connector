#!/usr/bin/env python
# Copyright 2017 Janos Czentye
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
import pprint
import re
import signal
from urlparse import urlparse

import requests
from flask import Flask, Response, request
from requests.exceptions import RequestException
from urllib3.exceptions import TimeoutError

from conversion.conversion import NFFGConverter
from conversion.converter import TNOVAConverter
from conversion.vnf_catalogue import VNFCatalogue
from nffg_lib.nffg import NFFG
from service.callback import CallbackManager
from service.service_mgr import ServiceManager, ServiceInstance
from util.colored_logger import VERBOSE, setup_flask_logging
from util.trail import MessageDumper
from virtualizer.virtualizer import Virtualizer
# Listening port
from virtualizer.virtualizer_mappings import Mappings, Mapping

LISTENING_PORT = 5000

# Connector configuration parameters
RO_URL = "http://localhost:8888/escape/orchestration"  # ESCAPE's top level
# REST-API

USE_VNF_STORE = False  # enable dynamic VNFD acquiring from VNF Store
VNF_STORE_URL = "http://localhost:8080/NFS/vnfds"
CATALOGUE_DIR = "vnf_catalogue"  # read VNFD from dir if VNFStore is disabled

USE_SERVICE_CATALOG = False  # enable dynamic NSD acquiring from service-catalog
SERVICE_CATALOG_URL = "http://localhost:42050/service/catalog"
NSD_DIR = "nsds"  # dir name used for storing received NSD files

SERVICE_NFFG_DIR = "services"  # dir name used for storing converted services

# Monitoring related parameters
MONITORING_URL = None
MONITORING_TIMEOUT = 5  # sec

# Communication related parameters
USE_CALLBACK = False
CALLBACK_URL = "http://localhost:9000/callback"
DYNAMIC_UPDATE_ENABLED = True  # Always request topology from RO for updates
USE_VIRTUALIZER_FORMAT = False
ENABLE_DIFF = True

# T-NOVA format constants
NS_ID_NAME = "ns_id"
MESSAGE_ID_NAME = "message-id"
CALLBACK_NAME = "call-back"

# Service request related constants
NFFG_SERVICE_RPC = "sg"
NFFG_TOPO_RPC = "topology"
VIRTUALIZER_TOPO_RPC = "get-config"
VIRTUALIZER_SERVICE_RPC = "edit-config"
VIRTUALIZER_MAPPINGS_RPC = "mappings"

# Other constants
PWD = os.path.realpath(os.path.dirname(__file__))
LOGGER_NAME = "TNOVAConnector"
HTTP_GLOBAL_TIMEOUT = 30  # sec

# Create REST-API handler app
app = Flask(LOGGER_NAME)

# Adjust Flask logging to common logging
setup_flask_logging(app=app)

# Create VNFCatalogue
catalogue = None
"""type: VNFCatalogue"""
# Create Service manager
service_mgr = None
"""type: ServiceManager"""
# Create converter
converter = None
"""type: TNOVAConverter"""
# Create Callback Manager
callback_mgr = None
"""type: CallbackManager"""


#############################################################################
# Define REST API calls
#############################################################################

@app.before_request
def request_logger ():
  app.logger.info(">>> Got HTTP %s request: %s --> %s, body: %s"
                  % (request.method, request.remote_addr, request.url,
                     len(request.data)))


@app.route("/nsd", methods=['POST'])
def register_nsd ():
  """
  REST-API function for NSD conversion and storing.
  Receive the defined NS from Marketplace, convert it into NFFG and store both
  description persistently.

  Rule: /nsd
  Method: POST
  Body: NSD in JSON

  :return: HTTP Response
  :rtype: :any:`flask.Response`
  """
  app.logger.debug("Called register_nsd() with path: POST /nsd")
  try:
    MessageDumper().dump_to_file(data=request.data, unique="nsd")
    path = service_mgr.store_nsd(raw=request.data)
    if path is None:
      Response(status=httplib.BAD_REQUEST)
    elif not service_mgr.convert_service(nsd_file=path):
      return Response(status=httplib.INTERNAL_SERVER_ERROR)
    # Conversion was ACCEPTED
    return Response(status=httplib.ACCEPTED)
  except:
    # Received unexpected exception
    return Response(status=httplib.INTERNAL_SERVER_ERROR)


@app.route("/vnfd", methods=['POST'])
def register_vnfd ():
  """
  REST-API function for VNFD storing. This function is defined for backward
  compatibility.
  Receives the defined VNF from Marketplace?? and store it persistently.
  NSD conversion could use these VNFD to convert the NSD, but currently the
  conversion use the remote VNFStore to acquire the necessary VNFD on-line.

  .. deprecated:: 2.0
    Use on-line VNFStore instead.

  Rule: /vnfd
  Method: POST
  Body: VNFD in JSON

  :return: HTTP Response
  :rtype: :any:`flask.Response`
  """
  app.logger.debug("Called register_vnfd() with path: POST /vnfd")
  try:
    MessageDumper().dump_to_file(data=request.data, unique="vnfd")
    app.logger.debug("Parsing request body...")
    data = json.loads(request.data)
    app.logger.log(VERBOSE, "Parsed body:\n%s" % pprint.pformat(data))
    # Filename based on the VNF ID
    filename = data['id']
    path = os.path.join(catalogue.VNF_CATALOGUE_DIR, "%s.nffg" % filename)
    # Write into file
    with open(path, 'w') as f:
      f.write(json.dumps(data))
    app.logger.info("Received VNFD has been saved: %s!" % path)
    # Response with success
    return Response(status=httplib.ACCEPTED)
  except ValueError:
    app.logger.error("Received data is not valid JSON!")
    app.logger.debug("Received body:\n%s" % request.data)
    return Response(status=httplib.BAD_REQUEST)
  except KeyError:
    app.logger.error("Received data is not valid VNFD!")
    app.logger.debug("Received body:\n%s" % request.data)
    return Response(status=httplib.BAD_REQUEST)


@app.route("/service", methods=['POST'])
def initiate_service ():
  """
  REST-API function for service initiation. The request contains the
  previously defined and converted NSD id. The stored NFFG will be send to
  ESCAPE's REST-API.

  Rule: /service
  Method: POST
  Body: e.g.
  {
    "callbackUrl": "http://172.16.46.129/serviceselection/service/selection/1",
    "flavour": "basic",
    "nap_id": "cwefvwewe",
    "ns_id": "591ad8f5e4b05b9a04730cef"
  }

  :return: HTTP Response
  :rtype: flask.Response
  """
  app.logger.debug("Called initiate_service() with path: POST /service")
  try:
    MessageDumper().dump_to_file(data=request.data, unique="service")
    app.logger.debug("Parsing request body...")
    instantiate_params = json.loads(request.data)
    app.logger.log(VERBOSE, "Parsed body:\n%s"
                   % pprint.pformat(instantiate_params))
    if NS_ID_NAME not in instantiate_params:
      app.logger.error(
        "Missing NSD id (%s) from service initiation request!" % NS_ID_NAME)
      return Response(status=httplib.BAD_REQUEST)
    ns_id = str(instantiate_params[NS_ID_NAME])
    app.logger.info("Received service initiation with id: %s" % ns_id)
  except ValueError:
    app.logger.error("Received POST params are not valid JSON!")
    app.logger.debug("Received body:\n%s" % request.data)
    return Response(status=httplib.BAD_REQUEST)
  ns_path = os.path.join(PWD, SERVICE_NFFG_DIR, "%s.nffg" % ns_id)
  # Create the service instantiation request, status->instantiated
  si = service_mgr.instantiate_ns(ns_id=ns_id,
                                  path=ns_path)
  if si is None or si.status == ServiceInstance.STATUS_ERROR:
    app.logger.error("Service instance creation has been failed!")
    return Response(status=httplib.INTERNAL_SERVER_ERROR)
  sg = si.sg
  app.logger.debug("Generated NF IDs:\n%s" % pprint.pformat(si.binding))
  if sg is None:
    service_mgr.set_service_status(id=si.id,
                                   status=ServiceInstance.STATUS_ERROR)
    return Response(status=httplib.NOT_FOUND)
  app.logger.info("Enforce Service instance parameters on loaded service...")
  app.logger.debug("Detected Service Instance id: %s" % si.id)
  # Set ADD mode
  sg.mode = NFFG.MODE_ADD
  app.logger.debug("Set mapping mode: %s" % sg.mode)
  params = {MESSAGE_ID_NAME: si.id}
  app.logger.debug("Adapt placement criteria...")
  converter.setup_placement_criteria(nffg=sg, params=instantiate_params)
  converter.setup_metadata(nffg=sg, params=instantiate_params)
  app.logger.debug("Using explicit message-id: %s" % params[MESSAGE_ID_NAME])
  app.logger.debug("Request topology view from RO...")
  topo = _get_topology_view()
  if topo is None:
    app.logger.error("Topology view is missing!")
    return Response(status=httplib.INTERNAL_SERVER_ERROR,
                    response=json.dumps({"error": "RO is not available!",
                                         "RO": RO_URL}))
  service_mgr.update_sg_hops_from_ro(si=si, topo=topo,
                                     virtualizer_enabled=USE_VIRTUALIZER_FORMAT)
  sg = si.update_sg_hop_ids(log=log)
  # Setup callback if it's necessary
  if USE_CALLBACK:
    app.logger.debug("Set callback URL: %s" % callback_mgr.url)
    params[CALLBACK_NAME] = callback_mgr.url
  # Setup format-related parameters
  app.logger.log(VERBOSE, "Loaded Service Instance:\n%s" % sg.dump())
  if USE_VIRTUALIZER_FORMAT:
    app.logger.info("Virtualizer format enabled!")
    # Prepare REST call parameters
    service_request_url = os.path.join(RO_URL, VIRTUALIZER_SERVICE_RPC)
    headers = {"Content-Type": "application/xml"}
    virt_srv = _convert_service_request(service_graph=sg,
                                        virt_topo=topo)
    if virt_srv is None:
      service_mgr.set_service_status(id=si.id,
                                     status=ServiceInstance.STATUS_ERROR)
      return Response(status=httplib.INTERNAL_SERVER_ERROR,
                      response=json.dumps({"error": "RO is not available!",
                                           "RO": RO_URL}))
    raw_data = virt_srv.xml()
  else:
    service_request_url = os.path.join(RO_URL, NFFG_SERVICE_RPC)
    headers = {"Content-Type": "application/json"}
    raw_data = sg.dump()
  # Backup modified service graph
  si.update_sg(sg=sg)
  app.logger.debug("Request stat:\n%s" % sg.get_stat())
  # Sending service request
  app.logger.debug("Send service request to RO on: %s" % service_request_url)
  # Try to orchestrate the service instance
  try:
    if USE_CALLBACK:
      cb = callback_mgr.subscribe_callback(hook=None,
                                           cb_id=si.id,
                                           type="SERVICE")
      requests.post(url=service_request_url,
                    headers=headers,
                    params=params,
                    data=raw_data,
                    allow_redirects=False,
                    timeout=HTTP_GLOBAL_TIMEOUT)
      MessageDumper().dump_to_file(data=raw_data, unique="service-out-RO")
      # Waiting for callback
      cb = callback_mgr.wait_for_callback(callback=cb)
      if cb.result_code == 0:
        app.logger.error("Callback for request: %s exceeded timeout(%s)!"
                         % (cb.callback_id, callback_mgr.wait_timeout))
        # Something went wrong, status->error_creating
        service_mgr.set_service_status(id=si.id,
                                       status=ServiceInstance.STATUS_ERROR)
        app.logger.debug("Send back TIMEOUT result...")
        _status = httplib.REQUEST_TIMEOUT
      else:
        if 200 <= cb.result_code < 300:
          app.logger.info("Service initiation has been forwarded with result:"
                          " %s" % cb.result_code)
          service_mgr.set_service_status(id=si.id,
                                         status=ServiceInstance.STATUS_START)
        else:
          app.logger.error("Service initiation has been failed! "
                           "Got status code: %s" % cb.result_code)
          # Something went wrong, status->error_creating
          service_mgr.set_service_status(id=si.id,
                                         status=ServiceInstance.STATUS_ERROR)
          app.logger.debug(
            "Send back callback result code: %s" % cb.result_code)
        # Use status code that received from callback
        _status = cb.result_code
    else:
      ret = requests.post(url=service_request_url,
                          headers=headers,
                          params=params,
                          data=raw_data,
                          allow_redirects=False,
                          timeout=HTTP_GLOBAL_TIMEOUT)
      MessageDumper().dump_to_file(data=raw_data, unique="service-out-RO")
      # Check result
      if ret.status_code == httplib.ACCEPTED:
        app.logger.info("Service initiation has been forwarded with result: "
                        "%s" % ret.status_code)
        # Due to the limitation of the current ESCAPE version, we can assume
        # that the service request was successful, status->running
        service_mgr.set_service_status(id=si.id,
                                       status=ServiceInstance.STATUS_START)
      else:
        app.logger.error("Service initiation has been failed! "
                         "Got status code: %s" % ret.status_code)
        # Something went wrong, status->error_creating
        service_mgr.set_service_status(id=si.id,
                                       status=ServiceInstance.STATUS_ERROR)
        app.logger.debug("Send back RO result code: %s" % ret.status_code)
      # Use status code that received from ESCAPE
      _status = ret.status_code
    if service_mgr.get_service_status(si.id) == si.STATUS_START:
      if 'callbackUrl' in instantiate_params:
        app.logger.debug("Collect callback info for service-selection...")
        cb_url = instantiate_params['callbackUrl']
        app.logger.debug("Detected callback URL: %s" % cb_url)
        data = _collect_si_callback_data(si=si,
                                         req_params=instantiate_params)
        app.logger.log(VERBOSE, "Collected callback data:\n%s"
                       % pprint.pformat(data))
        raw_data = json.dumps(data)
        try:
          ret = requests.post(url=cb_url,
                              headers={"Content-Type": "application/json"},
                              data=raw_data,
                              allow_redirects=False,
                              timeout=HTTP_GLOBAL_TIMEOUT)
          MessageDumper().dump_to_file(data=raw_data, unique="service-callback")
          if ret.status_code == httplib.OK:
            app.logger.debug("Callback result: %s" % ret.text)
          else:
            app.logger.warning("Received unexpected result for callback: "
                               "%s - %s" % (ret.status_code,
                                            ret.text if ret.text else ""))
        except RequestException:
          app.logger.error("Failed to send callback to %s" % cb_url)
      else:
        app.logger.warning("No callback URL was defined in the request!")
      # Notify Monitoring element if configured
      if MONITORING_URL:
        app.logger.info(
          "Monitoring notification is enabled! Send notification...")
        params = {'serviceid': si.id}
        try:
          requests.put(url=MONITORING_URL,
                       params=params,
                       allow_redirects=False,
                       timeout=MONITORING_TIMEOUT)
        except RequestException:
          app.logger.warning("Monitoring component(%s) is unreachable!" %
                             MONITORING_URL)
        except TimeoutError:
          app.logger.warning("Monitoring component(%s) is not available within "
                             "timeout: %s!!" % (MONITORING_URL,
                                                MONITORING_TIMEOUT))
    # Return the status code
    resp_data = json.dumps(si.get_json())
    MessageDumper().dump_to_file(data=resp_data, unique="service-response")
    return Response(status=_status,
                    response=json.dumps(si.get_json()))
  except RequestException:
    app.logger.error("RO is not available!")
    # Something went wrong, status->error_creating
    service_mgr.set_service_status(id=si.id,
                                   status=ServiceInstance.STATUS_ERROR)
    return Response(status=httplib.INTERNAL_SERVER_ERROR,
                    response=json.dumps(
                      {"error": "RO is not available!",
                       "RO": RO_URL}))
  except TimeoutError:
    app.logger.error("RO is not available within timeout: %s!"
                     % HTTP_GLOBAL_TIMEOUT)
    # Something went wrong, status->error_creating
    service_mgr.set_service_status(id=si.id,
                                   status=ServiceInstance.STATUS_ERROR)
    return Response(status=httplib.INTERNAL_SERVER_ERROR,
                    response=json.dumps(
                      {"error": "RO exceeded timeout!",
                       "RO": RO_URL,
                       "timeout": HTTP_GLOBAL_TIMEOUT}))
  except:
    app.logger.exception(
      "Got unexpected exception during service initiation!")
    # Something went wrong, status->error_creating
    service_mgr.set_service_status(id=si.id,
                                   status=ServiceInstance.STATUS_ERROR)
    return Response(status=httplib.BAD_REQUEST)


@app.route("/ns-instances", methods=['GET'])
def list_service_instances ():
  """
  REST-API function for service listing.

  Rule: /ns-instances
  Method: GET
  Body: None

  Sample response:
  [
    {
      "id": "456",
      "name": "name of the ns",
      "status": "stopped
    },
    ...
  ]

  :return: HTTP Response
  :rtype: flask.Response
  """
  app.logger.debug(
    "Called list_service_instances() with path: GET /ns-instances")
  if DYNAMIC_UPDATE_ENABLED:
    topo = _get_topology_view()
    if topo:
      service_mgr.update_si_addresses_from_ro(topo=topo)
  resp = service_mgr.get_services_status()
  app.logger.log(VERBOSE, "Sent response:\n%s" % pprint.pformat(resp))
  response_data = json.dumps(resp)
  MessageDumper().dump_to_file(data=response_data,
                               unique="ns-instances-response")
  return Response(status=httplib.OK,
                  content_type="application/json",
                  response=response_data)


@app.route("/ns-instances/<instance_id>/terminate", methods=['PUT'])
def terminate_service (instance_id):
  """
  REST-API function for service deletion. The request URL contains the
  previously initiated NSD id. The stored NFFG will be send to
  ESCAPE's REST-API.

  Rule: /ns-instances/{id}/terminate
  Method: PUT
  Body: None

  Sample response: 200 OK
  {
     "id":  "456",
     "ns-id": "987",
     "name":  "ESCAPE_NS",
     "status":  "stopped",
     "created_at":  "2014-11-21T14:18:09Z",
     "updated_at":  "2014-11-25T10:01:52Z"
  }

  :param instance_id: service instance ID
  :type instance_id: str
  :return: HTTP Response 200 OK
  :rtype: flask.Response
  """
  app.logger.debug(
    "Called terminate_service() with path: PUT /ns-instances/<id>/terminate")
  app.logger.info("Received service termination with id: %s" % instance_id)
  # Get managed service instance
  si = service_mgr.get_service(id=instance_id)
  if si is None:
    app.logger.error("Service instance: %s is not found!" % instance_id)
    return Response(status=httplib.NOT_FOUND)
  # If service instance is just created, stopped or error_created -> simply
  # delete
  app.logger.debug("Service status: %s" % si.status)
  if si.status != ServiceInstance.STATUS_START:
    app.logger.warning("Service instance: %s is not running! "
                       "Remove instance without service deletion from RO"
                       % instance_id)
    si = service_mgr.remove_service_instance(id=instance_id)
    resp = si.get_json()
    app.logger.log(VERBOSE, "Sent response:\n%s" % pprint.pformat(resp))
    MessageDumper().dump_to_file(data=json.dumps(resp),
                                 unique="terminate-response")
    return Response(status=httplib.OK,
                    content_type="application/json",
                    response=json.dumps(resp))
  app.logger.debug("Loading service instance...")
  sg = si.sg
  # Load NFFG from file
  if sg is None:
    app.logger.error("Service with id: %s is not found!" % instance_id)
    return Response(status=httplib.NOT_FOUND)
  # Set DELETE mode
  sg.mode = NFFG.MODE_DEL
  app.logger.debug("Set mapping mode: %s" % sg.mode)
  params = {MESSAGE_ID_NAME: "%s-DELETE" % si.id}
  app.logger.debug("Using explicit message-id: %s" % params[MESSAGE_ID_NAME])
  if USE_CALLBACK:
    app.logger.debug("Set callback URL: %s" % callback_mgr.url)
    params[CALLBACK_NAME] = callback_mgr.url
  if USE_VIRTUALIZER_FORMAT:
    app.logger.info("Virtualizer format enabled!")
    app.logger.debug("Request topology view from RO...")
    virt_topo = _get_topology_view()
    if virt_topo is None:
      app.logger.error("Topology view is missing!")
      return Response(status=httplib.INTERNAL_SERVER_ERROR,
                      response=json.dumps({"error": "RO is not available!",
                                           "RO": RO_URL}))
    # Prepare REST call parameters
    service_request_url = os.path.join(RO_URL, VIRTUALIZER_SERVICE_RPC)
    headers = {"Content-Type": "application/xml"}
    virt_srv = _convert_service_request(service_graph=sg,
                                        virt_topo=virt_topo,
                                        delete=True)
    if virt_srv is None:
      return Response(status=httplib.INTERNAL_SERVER_ERROR,
                      response=json.dumps({"error": "RO is not available!",
                                           "RO": RO_URL}))
    raw_data = virt_srv.xml()
  else:
    service_request_url = os.path.join(RO_URL, NFFG_SERVICE_RPC)
    headers = {"Content-Type": "application/json"}
    raw_data = sg.dump()
  app.logger.debug("Send request to RO on: %s" % service_request_url)
  try:
    if USE_CALLBACK:
      cb = callback_mgr.subscribe_callback(hook=None,
                                           cb_id=params[MESSAGE_ID_NAME],
                                           type="SERVICE")
      requests.post(url=service_request_url,
                    headers=headers,
                    params=params,
                    data=raw_data,
                    allow_redirects=False,
                    timeout=HTTP_GLOBAL_TIMEOUT)
      MessageDumper().dump_to_file(data=raw_data, unique="terminate-out-RO")
      # Waiting for callback
      cb = callback_mgr.wait_for_callback(callback=cb)
      if cb.result_code == 0:
        app.logger.warning("Callback for request: %s exceeded timeout(%s)"
                           % (cb.callback_id, callback_mgr.wait_timeout))
        # Something went wrong, status->error_creating
        service_mgr.set_service_status(id=si.id,
                                       status=ServiceInstance.STATUS_ERROR)
        log.debug("Send back TIMEOUT result...")
        return Response(status=httplib.REQUEST_TIMEOUT)
      else:
        if 200 <= cb.result_code < 300:
          app.logger.info("Service deletion has been forwarded with result: "
                          "%s" % cb.result_code)
          service_mgr.set_service_status(id=instance_id,
                                         status=ServiceInstance.STATUS_STOPPED)
          # Get and send Response
          resp = si.get_json()
          app.logger.log(VERBOSE, "Sent response:\n%s" % pprint.pformat(resp))
          MessageDumper().dump_to_file(data=json.dumps(resp),
                                       unique="terminate-response")
          return Response(status=httplib.OK,
                          content_type="application/json",
                          response=json.dumps(resp))
        else:
          app.logger.error("Got error from RO during service deletion! "
                           "Got status code: %s" % cb.result_code)
          # Something went wrong, status->error_creating
          service_mgr.set_service_status(id=si.id,
                                         status=ServiceInstance.STATUS_ERROR)
          app.logger.debug(
            "Send back callback result code: %s" % cb.result_code)
          return Response(status=cb.result_code)
    else:
      ret = requests.post(url=service_request_url,
                          headers=headers,
                          params=params,
                          data=raw_data,
                          allow_redirects=False,
                          timeout=HTTP_GLOBAL_TIMEOUT)
      MessageDumper().dump_to_file(data=raw_data, unique="terminate-out-RO")
      # Check result
      if ret.status_code == httplib.ACCEPTED:
        app.logger.info("Service termination has been forwarded with result: "
                        "%s" % ret.status_code)
        # Due to the limitation of the current ESCAPE version, we can assume
        # that the service request was successful, status->stopped
        si = service_mgr.remove_service_instance(id=instance_id)
        # Get and send Response
        resp = si.get_json()
        app.logger.log(VERBOSE, "Sent response:\n%s" % pprint.pformat(resp))
        MessageDumper().dump_to_file(data=json.dumps(resp),
                                     unique="terminate-response")
        return Response(status=httplib.OK,
                        content_type="application/json",
                        response=json.dumps(resp))
      else:
        app.logger.error("Got error from RO during service deletion! "
                         "Got status code: %s" % ret.status_code)
        # Something went wrong, status->error_creating
        service_mgr.set_service_status(id=si.id,
                                       status=ServiceInstance.STATUS_ERROR)
        app.logger.debug("Send back RO result code: %s" % ret.status_code)
        # Use status code that received from ESCAPE
        return Response(status=ret.status_code)
  except RequestException:
    app.logger.error("RO(%s) is not available!" % RO_URL)
    return Response(status=httplib.INTERNAL_SERVER_ERROR,
                    response=json.dumps(
                      {"error": "RO is not available!",
                       "RO": RO_URL}))
  except:
    app.logger.exception(
      "Got unexpected exception during service termination!")
    return Response(status=httplib.INTERNAL_SERVER_ERROR)


#############################################################################
# Proxy calls
#############################################################################

@app.route("/get-config", methods=['GET', 'POST'])
def get_config ():
  app.logger.debug("Called get_config() with path: GET,POST /get-config")
  topo = _get_topology_view(force_virtualizer=True)
  if topo is not None:
    # topo = topo.json()
    # app.logger.debug("Converted response:\n%s" % topo)
    topo = topo.xml()
    MessageDumper().dump_to_file(data=topo, unique="get-config-response")
    return Response(status=httplib.OK,
                    content_type="application/xml",
                    response=topo)
  else:
    return Response(status=httplib.INTERNAL_SERVER_ERROR)


@app.route("/mappings", methods=['POST'])
def mappings ():
  app.logger.debug("Called mappings() with path: POST /mappings")
  body = request.data
  if body is None:
    app.logger.error("Missing request body!")
    return Response(status=httplib.BAD_REQUEST)
  mapping = _get_mappings(data=body)
  if mapping is not None:
    # mapping = mapping.json()
    # app.logger.log(VERBOSE, "Converted mappings:\n%s" % mapping)
    mapping = mapping.xml()
    MessageDumper().dump_to_file(data=mapping, unique="mappings-response")
    return Response(status=httplib.OK,
                    content_type="application/xml",
                    response=mapping)
  else:
    return Response(status=httplib.INTERNAL_SERVER_ERROR)


def _generate_mappings_request (nffg):
  _mappings = Mappings()
  node_id = "SingleBiSBiS"
  app.logger.debug("Found node ID for /mapping: %s" % node_id)
  slice_id_tag = RO_URL.split('/')
  if slice_id_tag[-2] == "ro":
    app.logger.debug("Found slice ID for /mappings: %s" % slice_id_tag[-1])
    slice_id_tag = "[id=%s]" % slice_id_tag[-1]
  else:
    app.logger.warning("Using NO slice for /mapping...")
    slice_id_tag = ""
  M_TEMPLATE = "/virtualizer%s/nodes/node[id=%s]/NF_instances/node[id=%s]"
  for nf in nffg.nfs:
    _mappings.add(Mapping(object=M_TEMPLATE % (slice_id_tag, node_id, nf.id)))
  return _mappings


@app.route("/mapping-info/<service_id>", methods=['GET', 'POST'])
def mapping_info (service_id):
  app.logger.debug(
    "Called mapping_info() with path: GET /mapping-info/<service_id>")
  app.logger.info("Received mapping-info with id: %s" % service_id)
  response = {"service_id": service_id}
  # Get the internal Service Instance
  si = service_mgr.get_service(id=service_id)
  if si is None:
    app.logger.error("Service with id: %s is missing!" % service_id)
    return Response(status=httplib.OK,
                    content_type="application/json",
                    response=response)
  # Generate the mappings request for the SI
  mappings_req = _generate_mappings_request(nffg=si.sg)
  mappings = _get_mappings(data=mappings_req.xml())
  if mappings is None:
    app.logger.error("Mapping response from RO is missing!!")
    return Response(status=httplib.OK,
                    content_type="application/json",
                    response=response)
  response["mapping"] = []
  NODE_NF_PATTERN = r'.*nodes/node\[id=(.*?)\]/NF_instances/node\[id=(.*?)\]'
  mapping_regex = re.compile(NODE_NF_PATTERN)
  for mapping in mappings:
    t_path = mapping.target.object.get_value()
    t_domain = mapping.target.domain.get_value()
    node, nf = mapping_regex.match(t_path).group(1, 2)
    domain, url = t_domain.split('@', 1)
    nf_entry = {"bisbis": {"url": url,
                           "domain": domain,
                           "id": node},
                "nf": {"id": nf,
                       "ports": []}}
    try:
      for p in si.sg[nf].ports:
        nf_entry["nf"]["ports"].append({"id", p.id})
    except Exception:
      app.logger.warning("Port not found for NF: %s" % nf)
    response["mapping"].append(nf_entry)
  resp_data = json.dumps(response)
  MessageDumper().dump_to_file(data=resp_data,
                               unique="mapping-info")
  return Response(status=httplib.OK,
                  content_type="application/json",
                  response=resp_data)


@app.route("/placement-info/", methods=['GET'], strict_slashes=False)
def placement_info ():
  app.logger.debug("Called placement_info() with path: GET /placement-info")
  topo = _get_topology_view(force_virtualizer=True)
  if topo is not None:
    data = _get_internet_saps(virtualizer=topo)
    if data is not None:
      resp_data = json.dumps(data)
      MessageDumper().dump_to_file(data=resp_data,
                                   unique="placement-info-response")
      return Response(status=httplib.OK,
                      content_type="application/json",
                      response=resp_data)
    else:
      return Response(status=httplib.INTERNAL_SERVER_ERROR)
  else:
    return Response(status=httplib.INTERNAL_SERVER_ERROR)


#############################################################################
# Helper functions
#############################################################################

def _collect_si_callback_data (si, req_params):
  """
  
  :param si: 
  :param req_params: 
  :return: 
  """
  data = si.get_json()
  app.logger.debug("Collected service instance info:\n%s" % data)
  data['nsd_id'] = data.pop('ns-id')
  data['descriptor_reference'] = data['nsd_id']
  if 'callbackUrl' in req_params:
    data['marketplace_callback'] = str(req_params['callbackUrl'])
    data['notification'] = str(req_params['callbackUrl'])
    app.logger.debug("Set callback URL: %s" % data['notification'])
  else:
    app.logger.warning("Missing callback URL: 'callbackUrl' "
                       "from request parameters: %s!" % req_params)
  if 'flavour' in req_params:
    data['service_deployment_flavour'] = str(req_params['flavour'])
    app.logger.debug("Set flavour: %s" % data['service_deployment_flavour'])
  else:
    app.logger.warning("Missing flavour: 'flavour' "
                       "from request parameters: %s!" % req_params)
  vnf_addresses = data.pop('vnf_addresses', [])
  sg = si.get_sg()
  if sg is None:
    app.logger.error("Service Graph is missing from Service Instance: %s!" % si)
    return data
  data['vnfrs'] = []
  for nf in sg.nfs:
    nf_item = dict(pop_id="N/A",  # PoP where the instance is deployed
                   status="INSTANTIATED",  # default in case of ESCAPE
                   vnfr_id=nf.id,  # instance ID of NF
                   vnfi_id=[nf.id])  # ID of the VM once instantiated
    # vnf_wrapper = catalogue.get_by_type(nf.functional_type)
    if nf.has_metadata("store_id"):
      nf_item['vnfd_id'] = nf.get_metadata("store_id")
      app.logger.debug(
        "Detected VNFD id from metadata: %s" % nf_item['vnfd_id'])
    else:
      try:
        name, num, si_id = str(nf.id).rsplit('_', 2)
      except:
        name, num, si_id = None, None, None
      vnf_wrapper = catalogue.get_by_name(name=name)
      if vnf_wrapper is None:
        app.logger.error("Missing VNF: %s!" % name)
        continue
      nf_item['vnfd_id'] = str(vnf_wrapper.id)
      app.logger.debug("Detected VNFD id from NF name: %s" % nf_item['vnfd_id'])
    if nf.id in vnf_addresses:
      nf_item['vnf_addresses'] = vnf_addresses[nf.id]
      app.logger.debug("Detected addresses: %s" % nf_item['vnf_addresses'])
    else:
      nf_item['vnf_addresses'] = {}
    data['vnfrs'].append(nf_item)
  return data


def _replace_port (url, port):
  """
  
  :param url: 
  :param port:
  :return: 
  """
  parsed = urlparse(url)
  return parsed._replace(netloc=parsed.netloc.replace(str(parsed.port),
                                                      str(port))).geturl()


def _get_topology_view (force_virtualizer=False):
  """
  Request and return with the topology provided by the RO.

  :return: requested and parser topology
  :rtype: :class:`Virtualizer` or :class:`NFFG`
  """
  if force_virtualizer or USE_VIRTUALIZER_FORMAT:
    topo_request_url = os.path.join(RO_URL, VIRTUALIZER_TOPO_RPC)
  else:
    topo_request_url = os.path.join(RO_URL, NFFG_TOPO_RPC)
  app.logger.debug("Send topo request to RO on: %s" % topo_request_url)
  try:
    ret = requests.get(url=topo_request_url,
                       allow_redirects=False,
                       timeout=HTTP_GLOBAL_TIMEOUT)
    if ret.status_code != 200:
      app.logger.error(
        "Something went wrong during requesting topo! Got %s" % ret.status_code)
      return
    MessageDumper().dump_to_file(data=ret.text, unique="RO-get-config")
    if force_virtualizer or USE_VIRTUALIZER_FORMAT:
      try:
        topo = Virtualizer.parse_from_text(text=ret.text)
        app.logger.log(VERBOSE, "Received topology:\n%s" % topo.xml())
        return topo
      except Exception as e:
        app.logger.error("Something went wrong during topo parsing "
                         "into Virtualizer:\n%s" % e)
    else:
      try:
        topo = NFFG.parse(raw_data=ret.text)
        app.logger.log(VERBOSE, "Received topology:\n%s" % topo.dump())
        return topo
      except Exception as e:
        app.logger.error("Something went wrong during topo parsing "
                         "into NFFG:\n%s" % e)
  except RequestException:
    app.logger.error("RO is not available!")


def _get_internet_saps (virtualizer):
  """
  
  :param virtualizer: 
  :return: 
  """
  internet_saps = set()
  for node in virtualizer.nodes:
    for port in node.ports:
      if port.sap_data.role.get_as_text() == 'provider':
        internet_saps.add(port.sap.get_value())
    for vnf in node.NF_instances:
      for port in vnf.ports:
        if port.sap_data.role.get_as_text() == 'provider':
          internet_saps.add(port.sap.get_value())
  return list(internet_saps)


def _get_mappings (data):
  mappings_request_url = os.path.join(RO_URL, VIRTUALIZER_MAPPINGS_RPC)
  app.logger.debug("Send mappings request to RO on: %s" % mappings_request_url)
  try:
    ret = requests.post(url=mappings_request_url,
                        headers={"Content-Type": "application/xml"},
                        data=data,
                        allow_redirects=False,
                        timeout=HTTP_GLOBAL_TIMEOUT)
    MessageDumper().dump_to_file(data=ret.text, unique="RO-mappings")
    mappings = Mappings.parse_from_text(text=ret.text)
    app.logger.log(VERBOSE, "Received mapping:\n%s" % mappings.xml())
    return mappings
  except RequestException:
    app.logger.error("RO is not available!")


def _convert_service_request (service_graph, virt_topo, delete=False):
  """
  Convert given service request into Virtualizer format.
  Base Virtualizer is requested from RO.

  :param service_graph: service request
  :type service_graph: :class:`NFFG`
  :param delete: delete service request instead of adding to base virtualizer
  :type delete: bool
  :return: converted service request
  :rtype: :class:`Virtualizer`
  """
  if virt_topo is None:
    app.logger.error("Topology view is missing!")
    return
  if not delete:
    app.logger.debug("Start service request (INITIATE) conversion...")
    nc = NFFGConverter(logger=app.logger)
    srv_virtualizer = nc.convert_service_request_init(request=service_graph,
                                                      base=virt_topo,
                                                      reinstall=False)
  else:
    app.logger.debug("Start service request (DELETE) conversion...")
    nc = NFFGConverter(logger=app.logger)
    srv_virtualizer = nc.convert_service_request_del(request=service_graph,
                                                     base=virt_topo)
  app.logger.log(VERBOSE, "Converted request:\n%s" % srv_virtualizer.xml())
  if ENABLE_DIFF:
    app.logger.debug("Diff format enabled! Calculate diff...")
    # Avoid undesired replace from different relative/absolute leafrefs
    virt_topo.convert_leafrefs_to_relative_path()
    srv_virtualizer.convert_leafrefs_to_relative_path()
    # Avoid undesired "replace" for id and name
    virt_topo.id.set_value(srv_virtualizer.id.get_value())
    virt_topo.name.set_value(srv_virtualizer.name.get_value())
    # srv_virtualizer = Virtualizer.parse_from_text(srv_virtualizer.xml())
    srv_virtualizer = virt_topo.diff(srv_virtualizer)
    app.logger.log(VERBOSE, "Calculated diff:\n%s" % srv_virtualizer.xml())
  return srv_virtualizer


def _shutdown ():
  """
  Shutdown running servers.
  
  :return: None
  """
  # Shutdown Callback Manager
  callback_mgr.shutdown()
  # No correct way to shutdown Flask - WTF??


def _sigterm_handler (sig, stack):
  """
  Specific signal handler for SIGTERM to stop the connector by transforming the
  received signal to SIGINT.

  :param sig: received signal
  :param stack: stack frame
  :return: None
  """
  print "Received SIGTERM"
  os.kill(os.getpid(), signal.SIGINT)


def main ():
  """
  Main entry point of T-NOVA Connector.

  :return: None
  """
  # Register signal handler for SIGTERM used by Docker
  signal.signal(signal.SIGTERM, _sigterm_handler)
  # Entry point of main, start components
  app.logger.info("Initialize components...")
  try:
    global catalogue
    global service_mgr
    global converter
    global callback_mgr
    # Create Catalogue for VNFDs
    catalogue = VNFCatalogue(use_remote=USE_VNF_STORE,
                             vnf_store_url=VNF_STORE_URL,
                             cache_dir=os.path.realpath(
                               PWD + "/" + CATALOGUE_DIR),
                             logger=app.logger)
    catalogue.initialize()
    # Create converter
    converter = TNOVAConverter(vnf_catalogue=catalogue,
                               logger=app.logger)
    converter.initialize()
    # Create Service manager
    service_mgr = ServiceManager(converter=converter,
                                 use_remote=USE_SERVICE_CATALOG,
                                 service_catalog_url=SERVICE_CATALOG_URL,
                                 cache_dir=os.path.realpath(
                                   PWD + "/" + SERVICE_NFFG_DIR),
                                 nsd_dir=os.path.realpath(
                                   PWD + "/" + NSD_DIR),
                                 logger=app.logger)
    service_mgr.initialize()
    # Create Callback Manager
    callback_mgr = CallbackManager(domain_name="RO",
                                   callback_url=CALLBACK_URL,
                                   logger=app.logger.getChild("callback"),
                                   timeout=HTTP_GLOBAL_TIMEOUT)
    if USE_CALLBACK:
      callback_mgr.start()
    # Start Flask
    app.run(host='0.0.0.0', port=LISTENING_PORT, use_reloader=False)
  except KeyboardInterrupt:
    _shutdown()


if __name__ == "__main__":
  # Parse initial arguments
  parser = argparse.ArgumentParser(
    description="TNOVAConnector: Middleware component which make the "
                "connection between Marketplace and RO with automatic "
                "request conversion",
    add_help=True)
  parser.add_argument("-d", "--debug", action="count", default=0,
                      help="run in debug mode (can use multiple times for more "
                           "verbose logging, default logging level: INFO)")
  parser.add_argument("-c", "--callback", action="store", type=str,
                      metavar="URL", default="", nargs="?",
                      help="enable callbacks from the RO with given URL, "
                           "default: %s" % CALLBACK_URL)
  parser.add_argument("-m", "--monitoring", action="store", type=str,
                      default=None, metavar="URL",
                      help="URL of the monitoring component, default: None")
  parser.add_argument("-r", "--ro", action="store", type=str, default=False,
                      metavar="URL", help="RO's full URL, default: %s" % RO_URL)
  parser.add_argument("-p", "--port", action="store", type=int,
                      help="REST-API port, default: %s" % LISTENING_PORT)
  parser.add_argument("-s", "--vnfstore", action="store", type=str,
                      help="enable remote VNFStore with given full URL, "
                           "default: %s" % VNF_STORE_URL)
  parser.add_argument("-S", "--servicecatalog", action="store", type=str,
                      help="enable remote Service Catalog with given full URL, "
                           "default: %s" % SERVICE_CATALOG_URL)
  parser.add_argument("-t", "--timeout", action="store", type=int, metavar="t",
                      help="timeout in sec for HTTP communication, default: %ss"
                           % HTTP_GLOBAL_TIMEOUT)
  parser.add_argument("-v", "--virtualizer", action="store_true", default=False,
                      help="enable Virtualizer format, default: %s"
                           % USE_VIRTUALIZER_FORMAT)

  args = parser.parse_args()

  # Get logging level
  if args.debug == 0:
    level = logging.INFO
  elif args.debug == 1:
    level = logging.DEBUG
  else:
    level = VERBOSE

  # Get main TNOVAConnector logger
  log = logging.getLogger(LOGGER_NAME)
  log.setLevel(level=level)
  log.info("Set logging level: %s",
           logging.getLevelName(log.getEffectiveLevel()))

  # Set timeout
  if args.timeout:
    log.info("Using explicit timeout value: %ss" % args.timeout)
    HTTP_GLOBAL_TIMEOUT = args.timeout

  if args.port:
    LISTENING_PORT = args.port
    log.info("Using explicit listening port: %s" % LISTENING_PORT)
  else:
    log.debug("Using default listening port: %s" % LISTENING_PORT)
  # Set RO_URL
  if args.ro:
    RO_URL = args.ro
    log.info("Set RO URL from command line: %s" % RO_URL)
  elif 'RO_URL' in os.environ:
    RO_URL = os.environ.get('RO_URL')
    log.info("Set RO's URL from environment variable "
             "(RO_URL): %s" % RO_URL)
  else:
    log.info("Use default value for RO's URL: %s" % RO_URL)
  # Set VNF_STORE_URL
  if args.vnfstore:
    VNF_STORE_URL = args.vnfstore
    USE_VNF_STORE = True
    log.info("Set VNFStore's URL from command line: %s" % VNF_STORE_URL)
  elif 'VNF_STORE_URL' in os.environ:
    VNF_STORE_URL = os.environ.get('VNF_STORE_URL')
    USE_VNF_STORE = True
    log.info("Set VNFStore's URL from environment variable "
             "(VNF_STORE_URL): %s" % VNF_STORE_URL)
  else:
    log.info("Disable using remote VNF Store")
  # Set VNF_STORE_URL
  if args.servicecatalog:
    SERVICE_CATALOG_URL = args.servicecatalog
    USE_SERVICE_CATALOG = True
    log.debug("Set Service Catalog's URL from command line: %s"
              % SERVICE_CATALOG_URL)
  elif 'SERVICE_CATALOG_URL' in os.environ:
    SERVICE_CATALOG_URL = os.environ.get('SERVICE_CATALOG_URL')
    USE_SERVICE_CATALOG = True
    log.info("Set Service Catalog's URL from environment variable "
             "(SERVICE_CATALOG_URL): %s" % SERVICE_CATALOG_URL)
  else:
    log.info("Disable using remote Service Catalog")
  # Set callbacks
  if args.callback:
    CALLBACK_URL = args.callback
    USE_CALLBACK = True
    log.info("Enable callbacks with explicit URL from command line: %s"
             % CALLBACK_URL)
  elif 'CALLBACK_URL' in os.environ:
    CALLBACK_URL = os.environ.get('CALLBACK_URL')
    USE_CALLBACK = True
    log.info("Set using callbacks from environment variable "
             "(CALLBACK_URL): %s" % CALLBACK_URL)
  elif args.callback is None:
    CALLBACK_URL = args.callback
    USE_CALLBACK = True
    log.info("Enable callbacks with default URL")
  else:
    log.debug("Disable callback-based communication")
  # Store monitoring URL
  if args.monitoring:
    MONITORING_URL = args.monitoring
    log.info("Enable monitoring notification with explicit URL from command "
             "line: %s" % MONITORING_URL)
  elif 'MONITORING_URL' in os.environ:
    MONITORING_URL = os.environ.get('MONITORING_URL')
    log.info("Enable monitoring notifications from environment variable "
             "(MONITORING_URL): %s" % MONITORING_URL)
  else:
    log.info("Disable monitoring notifications")
  # Virtualizer format
  if args.virtualizer:
    USE_VIRTUALIZER_FORMAT = args.virtualizer
    log.info("Enable Virtualizer format from command line: %s" %
             USE_VIRTUALIZER_FORMAT)
  elif 'USE_VIRTUALIZER_FORMAT' in os.environ:
    USE_VIRTUALIZER_FORMAT = os.environ.get('USE_VIRTUALIZER_FORMAT')
    log.info("Enable Virtualizer format from environment variable "
             "(USE_VIRTUALIZER_FORMAT): %s" % USE_VIRTUALIZER_FORMAT)
  else:
    log.info("Used format for RO: NFFG")

  # Run TNOVAConnector
  main()
