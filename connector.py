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
import pprint
import signal

import requests
from flask import Flask, Response, request
from requests.exceptions import ConnectionError

from callback import CallbackManager
from colored_logger import ColoredLogger, VERBOSE
from conversion.conversion import convert_service_request
from conversion.converter import TNOVAConverter
from conversion.vnf_catalogue import VNFCatalogue, MissingVNFDException
from nffg_lib.nffg import NFFG
from service_mgr import ServiceManager, ServiceInstance
# Connector configuration parameters
from virtualizer.virtualizer import Virtualizer

RO_URL = "http://localhost:8008/escape"  # ESCAPE's top level REST-API
VNF_STORE_URL = "http://localhost:8080/NFS/vnfds"

USE_VNF_STORE = False  # enable dynamic VNFD acquiring from VNF Store
NSD_DIR = "nsds"  # dir name used for storing received NSD files
SERVICE_NFFG_DIR = "services"  # dir name used for storing converted services
CATALOGUE_DIR = "vnf_catalogue"  # read VNFDs from dir if VNF Store is disabled

# Monitoring related parameters
MONITORING_URL = None

# Communication related parameters
USE_CALLBACK = False
CALLBACK_URL = None
USE_VIRTUALIZER_FORMAT = True
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

# Other constants
PWD = os.path.realpath(os.path.dirname(__file__))
POST_HEADERS = {"Content-Type": "application/json"}
LOGGER_NAME = "TNOVAConnector"
HTTP_GLOBAL_TIMEOUT = 5


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


# Register handler
signal.signal(signal.SIGTERM, _sigterm_handler)


def main ():
  """
  Main entry point of T-NOVA Connector.

  :return: None
  """
  # Create REST-API handler app
  app = Flask(LOGGER_NAME)
  # Adjust Flask logging to common logging
  app.logger.handlers[:] = [ColoredLogger.createHandler()]
  app.logger.propagate = False
  app.logger.setLevel(log.getEffectiveLevel())
  # Create Catalogue for VNFDs
  catalogue = VNFCatalogue(remote_store=USE_VNF_STORE,
                           url=VNF_STORE_URL,
                           catalogue_dir=CATALOGUE_DIR,
                           logger=app.logger)
  # Create converter
  converter = TNOVAConverter(vnf_catalogue=catalogue,
                             logger=app.logger)
  # Create Service manager
  service_mgr = ServiceManager(service_dir=os.path.join(PWD, SERVICE_NFFG_DIR),
                               ro_url=RO_URL,
                               logger=app.logger)
  # Create Callback Manager
  callback_mgr = CallbackManager(domain_name="RO",
                                 callback_url=CALLBACK_URL,
                                 log=app.logger)

  # Define REST API calls

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
    app.logger.log(VERBOSE, "Converted service:\n%s" % sg.dump())
    # Save result NFFG into a file
    sg_path = os.path.join(PWD, SERVICE_NFFG_DIR, "%s.nffg" % sg.id)
    with open(sg_path, 'w') as f:
      f.write(sg.dump())
    app.logger.info("Converted NFFG has been saved! Path: %s" % sg_path)
    return True

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
    app.logger.info("Call register_nsd() with path: POST /nsd")
    try:
      # Parse data as JSON
      app.logger.debug("Parsing request body...")
      data = json.loads(request.data)
      app.logger.log(VERBOSE, "Parsed body:\n%s" % pprint.pformat(data))
      # Filename based on the service ID
      filename = data['nsd']['id']
      path = os.path.join(PWD, NSD_DIR, "%s.json" % filename)
      # Write into file
      with open(path, 'w') as f:
        f.write(json.dumps(data, indent=2, sort_keys=True))
      app.logger.info("Received NSD has been saved into %s!" % path)
      if not convert_service(nsd_file=path):
        return Response(status=httplib.INTERNAL_SERVER_ERROR)
      # Response with 200 OK
      return Response(status=httplib.ACCEPTED)
    except ValueError:
      app.logger.exception("Received data is not valid JSON!")
      app.logger.debug("Received body:\n%s" % request.data)
      return Response(status=httplib.BAD_REQUEST)
    except KeyError:
      app.logger.exception("Received data is not valid NSD!")
      app.logger.debug("Received body:\n%s" % request.data)
      return Response(status=httplib.BAD_REQUEST)
    except MissingVNFDException:
      app.logger.exception("Unrecognisable VNFD has been found in NSD!")
      return Response(status=httplib.INTERNAL_SERVER_ERROR)
    except:
      app.logger.exception(
        "Got unexpected exception during NSD -> NFFG conversion!")
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
    app.logger.info("Call register_vnfd() with path: POST /vnfd")
    try:
      app.logger.debug("Parsing request body...")
      data = json.loads(request.data)
      app.logger.log(VERBOSE, "Parsed body:\n%s" % pprint.pformat(data))
      # Filename based on the VNF ID
      filename = data['id']
      path = os.path.join(PWD, CATALOGUE_DIR, "%s.nffg" % filename)
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
    Body: service request id in JSON object with key: "ns-id"

    :return: HTTP Response
    :rtype: flask.Response
    """
    app.logger.info("Call initiate_service() with path: POST /service")
    try:
      app.logger.debug("Parsing request body...")
      params = json.loads(request.data)
      app.logger.log(VERBOSE, "Parsed body:\n%s" % pprint.pformat(params))
      if NS_ID_NAME not in params:
        app.logger.error(
          "Missing NSD id (%s) from service initiation request!" % NS_ID_NAME)
        return Response(status=httplib.BAD_REQUEST)
      ns_id = params[NS_ID_NAME]
      app.logger.info("Received service initiation with id: %s" % ns_id)
    except ValueError:
      app.logger.error("Received POST params are not valid JSON!")
      app.logger.debug("Received body:\n%s" % request.data)
      return Response(status=httplib.BAD_REQUEST)
    ns_path = os.path.join(PWD, SERVICE_NFFG_DIR, "%s.nffg" % ns_id)
    # Create the service instantiation request, status->instantiated
    si = service_mgr.instantiate_ns(ns_id=ns_id,
                                    path=ns_path,
                                    status=ServiceInstance.STATUS_INST)
    if si is None:
      app.logger.error("Service instance creation has been failed!")
      return Response(status=httplib.INTERNAL_SERVER_ERROR)
    app.logger.debug("Loading Service Descriptor from file: %s..." % ns_path)
    sg = si.load_sg_from_file()
    if sg is None:
      app.logger.error("Service with id: %s is not found!" % ns_id)
      return Response(status=httplib.NOT_FOUND)
    # Set ADD mode
    sg.mode = NFFG.MODE_ADD
    app.logger.debug("Set mapping mode: %s" % sg.mode)
    params = {MESSAGE_ID_NAME: si.id}
    # Setup callback if it's necessary
    if USE_CALLBACK:
      app.logger.debug("Set callback URL: %s" % callback_mgr.url)
      params[CALLBACK_NAME] = callback_mgr.url
    app.logger.debug("Using explicit message-id: %s" % params[MESSAGE_ID_NAME])
    # Setup format-related parameters
    if USE_VIRTUALIZER_FORMAT:
      app.logger.info("Virtualizer format enabled! Start conversion...")
      app.logger.debug("Request topology view from RO...")
      topo = get_topology_view()
      if topo is None:
        app.logger.error("Topology view is missing!")
        return Response(status=httplib.INTERNAL_SERVER_ERROR,
                        response=json.dumps(
                          {"error": "RO is not available!",
                           "RO": RO_URL}))
      srv = convert_service_request(request=sg,
                                    base=topo,
                                    reinstall=False,
                                    log=app.logger)
      # Store converted XML
      vpath = si.path.rsplit('.', 1)[0] + ".xml"
      # Write into file
      with open(vpath, 'w') as f:
        f.write(srv.xml())
      app.logger.info("Converted Virtualizer has been saved into %s!" % vpath)
      # Prepare REST call parameters
      service_request_url = os.path.join(RO_URL, VIRTUALIZER_SERVICE_RPC)
      headers = {"Content-Type": "application/xml"}
      if ENABLE_DIFF:
        app.logger.debug("Diff format enabled! Calculate diff...")
        # Avoid undesired "replace" for id and name
        topo.id.set_value(srv.id.get_value())
        topo.name.set_value(srv.name.get_value())
        raw_data = topo.diff(srv).xml()
        app.logger.log(VERBOSE, "Calculated diff:\n%s" % raw_data)
      else:
        raw_data = srv.xml()
    else:
      service_request_url = os.path.join(RO_URL, NFFG_SERVICE_RPC)
      raw_data = sg.dump()
      headers = {"Content-Type": "application/json"}
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
                      timeout=HTTP_GLOBAL_TIMEOUT)
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
                            timeout=HTTP_GLOBAL_TIMEOUT)
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
      # Notify Monitoring element if configured
      if service_mgr.get_service_status(si.id) == si.STATUS_START:
        if MONITORING_URL:
          app.logger.info(
            "Monitoring notification is enabled! Send notification...")
          params = {'serviceid': si.id}
          try:
            requests.get(url=MONITORING_URL,
                         params=params,
                         timeout=HTTP_GLOBAL_TIMEOUT)
          except ConnectionError:
            app.logger.warning("Monitoring component(%s) is unreachable!" %
                               MONITORING_URL)
      # Return the status code
      return Response(status=_status)
    except ConnectionError:
      app.logger.error("RO is not available!")
      # Something went wrong, status->error_creating
      service_mgr.set_service_status(id=si.id,
                                     status=ServiceInstance.STATUS_ERROR)
      return Response(status=httplib.INTERNAL_SERVER_ERROR,
                      response=json.dumps(
                        {"error": "RO is not available!",
                         "RO": RO_URL}))
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
    app.logger.info(
      "Call list_service_instances() with path: GET /ns-instances")
    # services = service_mgr.get_running_services()
    resp = service_mgr.get_services_status()
    app.logger.log(VERBOSE, "Sent response:\n%s" % pprint.pformat(resp))
    return Response(status=httplib.OK,
                    content_type="application/json",
                    response=json.dumps(resp))

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
    app.logger.info(
      "Call terminate_service() with path: PUT /ns-instances/<id>/terminate")
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
      return Response(status=httplib.OK,
                      content_type="application/json",
                      response=json.dumps(resp))
    app.logger.debug("Loading service request from file: %s..." % si.path)
    sg = si.load_sg_from_file()
    # Load NFFG from file
    if sg is None:
      app.logger.error("Service with id: %s is not found!" % instance_id)
      return Response(status=httplib.NOT_FOUND)
    # Set DELETE mode
    sg.mode = NFFG.MODE_DEL
    params = {MESSAGE_ID_NAME: "%s-DELETE" % si.id}
    if USE_CALLBACK:
      app.logger.debug("Set callback URL: %s" % callback_mgr.url)
      params[CALLBACK_NAME] = callback_mgr.url
    app.logger.debug("Set mapping mode: %s" % sg.mode)
    app.logger.debug("Send request to RO on: %s" % RO_URL)
    app.logger.log(VERBOSE, "Forwarded deletion request:\n%s" % sg.dump())
    try:
      if USE_CALLBACK:
        cb = callback_mgr.subscribe_callback(hook=None,
                                             cb_id=si.id,
                                             type="SERVICE")
        requests.post(url=RO_URL,
                      headers=POST_HEADERS,
                      params=params,
                      json=sg.dump_to_json(),
                      timeout=HTTP_GLOBAL_TIMEOUT)
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
        ret = requests.post(url=RO_URL,
                            headers=POST_HEADERS,
                            params=params,
                            json=sg.dump_to_json(),
                            timeout=HTTP_GLOBAL_TIMEOUT)
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
    except ConnectionError:
      app.logger.error("RO(%s) is not available!" % RO_URL)
      return Response(status=httplib.INTERNAL_SERVER_ERROR,
                      response=json.dumps(
                        {"error": "RO is not available!",
                         "RO": RO_URL}))
    except:
      app.logger.exception(
        "Got unexpected exception during service termination!")
      return Response(status=httplib.INTERNAL_SERVER_ERROR)

  def get_topology_view ():
    """
    Request and return with the topology provided by the RO.
    
    :return: requested and parser topology
    :rtype: :class:`Virtualizer` or :class:`NFFG`
    """
    if USE_VIRTUALIZER_FORMAT:
      topo_request_url = os.path.join(RO_URL, VIRTUALIZER_TOPO_RPC)
    else:
      topo_request_url = os.path.join(RO_URL, NFFG_TOPO_RPC)
    app.logger.debug("Send topo request to RO on: %s" % topo_request_url)
    try:
      ret = requests.get(url=topo_request_url)
      if USE_VIRTUALIZER_FORMAT:
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
    except ConnectionError:
      app.logger.error("RO is not available!")

  def _shutdown ():
    """
    Shutdown running servers.
    
    :return: None
    """
    # Shutdown Callback Manager
    callback_mgr.shutdown()
    # No correct way to shutdown Flask

  # Entry point of main, start components

  try:
    # Start Callback Manager first
    if USE_CALLBACK:
      callback_mgr.start()
    # Start Flask
    app.run(host='0.0.0.0', port=args.port, debug=args.debug,
            use_reloader=False)
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
                      help="enables callbacks from the RO with given URL, "
                           "default: http://localhost:9000/callback")
  parser.add_argument("-m", "--monitoring", action="store", type=str,
                      default=None, metavar="URL",
                      help="URL of the monitoring component, default: None")
  parser.add_argument("-r", "--ro", action="store", type=str, default=False,
                      metavar="URL", help="RO's full URL, default: "
                                          "http://localhost:8008/escape/sg")
  parser.add_argument("-p", "--port", action="store", default=5000,
                      type=int, help="REST-API port (default: 5000)")
  parser.add_argument("-t", "--timeout", action="store", default=5,
                      type=int, help="timeout in sec for HTTP "
                                     "communication, default: 5s")
  parser.add_argument("-v", "--vnfs", action="store", type=str, default=False,
                      help="enables remote VNFStore with given full URL, "
                           "default: http://localhost:8080/NFS/vnfds")

  args = parser.parse_args()

  # Get logging level
  if args.debug == 0:
    level = logging.INFO
  elif args.debug == 1:
    level = logging.DEBUG
  else:
    level = VERBOSE

  # Configure root logging
  logging.addLevelName(VERBOSE, 'VERBOSE')
  log = logging.getLogger()
  log.addHandler(ColoredLogger.createHandler())
  log.setLevel(level)
  # Get main TNOVAConnector logger
  log = logging.getLogger(LOGGER_NAME)
  log.info("Set logging level: %s",
           logging.getLevelName(log.getEffectiveLevel()))

  # Set ESCAPE_URL
  if args.ro:
    RO_URL = args.ro
    log.debug("Set RO URL from command line: %s" % RO_URL)
  elif 'RO_URL' in os.environ:
    RO_URL = os.environ.get('RO_URL')
    log.info("Set RO's URL from environment variable (RO_URL): %s" % RO_URL)
  else:
    log.info("Use default value for RO's URL: %s" % RO_URL)
  # Set CATALOGUE_URL
  if args.vnfs:
    VNF_STORE_URL = args.vnfs
    USE_VNF_STORE = True
    log.info("Set VNFStore's URL from command line: %s" % VNF_STORE_URL)
  elif 'VNF_STORE_URL' in os.environ:
    VNF_STORE_URL = os.environ.get('VNF_STORE_URL')
    USE_VNF_STORE = True
    log.info(
      "Set VNFStore's URL from environment variable (VNF_STORE_URL): %s" %
      VNF_STORE_URL)
  else:
    log.info(
      "Use default value for VNFStore's URL: %s" % VNF_STORE_URL)
  # Set callbacks
  if args.callback:
    CALLBACK_URL = args.callback
    USE_CALLBACK = True
    log.info("Enable callbacks with explicit URL from command line: %s"
             % CALLBACK_URL)
  elif 'CALLBACK_URL' in os.environ:
    CALLBACK_URL = os.environ.get('CALLBACK_URL')
    USE_CALLBACK = True
    log.info("Set using callbacks from environment variable (CALLBACK_URL): %s"
             % CALLBACK_URL)
  elif args.callback is None:
    CALLBACK_URL = args.callback
    USE_CALLBACK = True
    log.info("Enable callbacks with default URL")
  else:
    log.info("Disable callback-based communication")
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

  # Run TNOVAConnector
  main()
