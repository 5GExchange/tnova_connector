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
import uuid

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


class ServiceInstance(object):
  """
  Container class for a service instance.
  """
  # Status constants
  STATUS_INIT = "init"  # between instantiation request and the provisioning
  STATUS_INSTANTIATED = "instantiated"  # provisioned, instantiated but not
  # running yet
  STATUS_START = "start"  # when everything worked as it should be
  STATUS_ERROR = "error_creating"  # in case of any error
  STATUS_STOPPED = "stopped"

  def __init__ (self, service_id, instance_id=None, name=None, status=None,
                path=None):
    self.service_id = service_id  # Converted NFFG the service created from
    # The id of the service instance
    self.instance_id = instance_id if instance_id else str(uuid.uuid1())
    self.name = name
    self.status = status if status else self.STATUS_INIT
    self.path = path


class ServiceManager(object):
  """
  Manager class for NSD instances.
  Very primitive.
  """
  LOGGER_NAME = "ServiceManager"
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
    self.log.info("Read default services from location: %s" % self.service_dir)
    for filename in os.listdir(self.service_dir):
      if not filename.startswith('.') and filename.endswith('.nffg'):
        service_id = os.path.splitext(filename)[0]
        self.log.debug("Detected service NFFG: %s" % service_id)

  def add_service (self, service_id, path=None, name=None,
                   status=ServiceInstance.STATUS_INIT):
    """
    Add service with optional status.

    :param service_id: service id
    :type service_id: str
    :param name: service name
    :type name: str
    :param status: service status (optional)
    :param path: path of the service NFFG
    :type path: str
    :return: instance id if success else None
    :rtype: str
    """
    try:
      sg = NFFG.parse_from_file(path)
    except IOError:
      self.log.warning("NFFG file for service instance creation is not found in"
                       " %s! Skip service processing..." % self.service_dir)
      return None
    si = ServiceInstance(service_id=service_id,
                         name=name if name else sg.name,
                         status=status,
                         path=path)
    self.services[si.instance_id] = si
    self.log.info("Add managed service: %s with instance id: %s " % (
      service_id, si.instance_id))
    return si.instance_id

  def set_service_status (self, instance_id, status):
    """
    Add status for service with given id.

    :param instance_id: service id
    :type instance_id: str
    :param status: service status
    :type status: str
    :return: None
    """
    if instance_id not in self.services:
      self.log.warning("Missing service instance: %s from ServiceManager!" %
                       instance_id)
    else:
      self.services[instance_id].status = status
      self.log.info("Status for service: %s updated with value: %s" %
                    (instance_id, status))

  def get_service (self, instance_id):
    """
    Return with service information given by id.

    :param instance_id: service id
    :type instance_id: str
    :return: service description dict
    :rtype: dict
    """
    if instance_id in self.services:
      return self.services[instance_id]
    else:
      self.log.warning("Missing service instance: %s from ServiceManager!" %
                       instance_id)

  def get_service_status (self, instance_id):
    """
    Return with service information given by id.

    :param instance_id: service id
    :type instance_id: str
    :return: service status
    :rtype: str
    """
    if instance_id in self.services:
      return self.services[instance_id].status
    else:
      self.log.warning("Missing service instance: %s from ServiceManager!" %
                       instance_id)

  def get_service_name (self, instance_id):
    """
    Return with service information given by id.

    :param instance_id: service id
    :type instance_id: str
    :return: service name
    :rtype: str
    """
    if instance_id in self.services:
      return self.services[instance_id].name
    else:
      self.log.warning("Missing service instance: %s from ServiceManager!" %
                       instance_id)

  def get_running_services_status (self):
    """
    Return with the running services.

    :return: running services
    :rtype: list
    """
    self.log.info("Collect running services from ServiceManager...")
    ret = []
    for instance_id in self.services:
      if self.services[instance_id].status == ServiceInstance.STATUS_START:
        ret.append({"id": instance_id,
                    "name": self.get_service_name(instance_id),
                    "status": self.get_service_status(instance_id)})
    return ret

  def get_services_status (self):
    """
    Return with the managed services.

    :return: all managed services
    :rtype: list
    """
    self.log.info("Collect managed services from ServiceManager...")
    ret = []
    for instance_id in self.services:
      ret.append({"id": instance_id,
                  "name": self.get_service_name(instance_id),
                  "status": self.get_service_status(instance_id)})
    return ret
