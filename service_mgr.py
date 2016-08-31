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
import logging
import os
import sys

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


class ServiceManager(object):
  """
  Manager class for NSD instances.
  Very primitive.
  """
  LOGGER_NAME = "ServiceManager"
  # Status constants
  STATUS_RUNNING = "RUNNING"
  STATUS_STOPPED = "STOPPED"
  # Default ESCAPE RUL
  ESCAPE_URL = "http://localhost:8008"

  def __init__ (self, service_dir, escape_url, logger=None):
    self.service_dir = service_dir
    self.ESCAPE_URL = escape_url
    # service-id: status
    self.services = {}
    if logger is not None:
      self.log = logger.getChild(self.LOGGER_NAME)
      # self.log.name = self.LOGGER_NAME
    else:
      logging.getLogger(self.__class__.__name__)
    self.initialize()

  def initialize (self):
    """
    Initialize NSDManager from persistent files.

    :return: None
    """
    self.log.info("Read saved services from location: %s" % self.service_dir)
    for filename in os.listdir(self.service_dir):
      if not filename.startswith('.') and filename.endswith('.nffg'):
        service_id = os.path.splitext(filename)[0]
        self.log.debug("Detected service NFFG: %s" % service_id)
        self.services[service_id] = {}

  def add_service (self, service_id, status=None):
    """
    Add service with optional status.

    :param service_id: service id
    :type service_id: str
    :param status: service status (optional)
    :return: None
    """
    if service_id in self.services:
      self.log.warning("Service: %s is already in ServiceManager! "
                       "Skip adding..." % service_id)
    if status is None:
      self.services[service_id] = {}
      self.log.info("Add managed service: %s" % service_id)
    else:
      self.services[service_id]['status'] = status
      self.log.info(
        "Add managed service: %s with status: %s " % (service_id, status))

  def set_service_status (self, service_id, status):
    """
    Add status for service with given id.

    :param service_id: service id
    :type service_id: str
    :param status: service status
    :type status: str
    :return: None
    """
    if service_id not in self.services:
      self.log.warning("Missing service: %s from ServiceManager!" % service_id)
    else:
      self.services[service_id]['status'] = status
      self.log.info("Status for service: %s updated with value: %s" %
                    (service_id, status))

  def get_service (self, service_id):
    """
    Return with service information given by id.

    :param service_id: service id
    :type service_id: str
    :return: service description dict
    :rtype: dict
    """
    if service_id in self.services:
      return self.services[service_id]
    else:
      self.log.warning("Missing service: %s from ServiceManager!" % service_id)

  def get_running_services (self):
    """
    Return with the running services.

    :return: running services
    :rtype: list
    """
    self.log.info("Collect running services from ServiceManager...")
    return [NFFG.parse_from_file(
      "%s.nffg" % os.path.join(self.service_dir, service_id))
            for service_id in self.services
            if 'status' in self.services[service_id] and
            self.services[service_id]['status'] ==
            ServiceManager.STATUS_RUNNING]
