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
import datetime
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
  STATUS_INST = "instantiated"  # provisioned, instantiated but not
  # running yet
  STATUS_START = "start"  # when everything worked as it should be
  STATUS_ERROR = "error_creating"  # in case of any error
  STATUS_STOPPED = "stopped"

  def __init__ (self, service_id, instance_id=None, name=None, path=None,
                status=None):
    self.id = instance_id if instance_id else str(uuid.uuid1())
    self.service_id = service_id  # Converted NFFG the service created from
    # The id of the service instance
    self.name = name
    self.path = path
    self.__status = status if status else self.STATUS_INIT
    self.created_at = datetime.datetime.fromtimestamp(
      os.path.getctime(self.path)).isoformat()
    self.updated_at = self.__touch()

  def __touch (self):
    """
    Update the updated_at attribute.

    :return: new value
    :rtype: str
    """
    self.updated_at = datetime.datetime.now().isoformat()

  @property
  def status (self):
    return self.__status

  @status.setter
  def status (self, value):
    self.__status = value
    self.__touch()

  def get_json (self):
    """
    Return the service instance in JSON format.

    :return: service instance description is JSON
    :rtype: dict
    """
    return {"id": self.id,
            "ns-id": self.service_id,
            "status": self.__status,
            "created_at": self.created_at,
            "updated_at": self.updated_at}

  def load_sg_from_file (self, path=None, mode=None):
    """
    Read and return the service description this service instance originated
    from.

    :param path: overrided path (optional)
    :type path: str
    :return: read NFFG
    :rtype: :any:`NFFG`
    """
    if path is None:
      path = self.path
    # Load NFFG from file
    try:
      nffg = NFFG.parse_from_file(path=path)
      # Rewrite the default SG id  to the instance id to be unique for ESCAPE
      nffg.id = self.id
      nffg.mode = mode
      return nffg
    except IOError:
      return None


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
    # service-id: ServiceInstance object
    self.instances = {}
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
    self.log.info("Read defined services from location: %s" % self.service_dir)
    for filename in os.listdir(self.service_dir):
      if not filename.startswith('.') and filename.endswith('.nffg'):
        service_id = os.path.splitext(filename)[0]
        self.log.debug("Detected service NFFG: %s" % service_id)

  def instantiate_ns (self, ns_id, path=None, name=None,
                      status=ServiceInstance.STATUS_INIT):
    """
    Create a service (NS) instance with optional status.

    :param ns_id: service id
    :type ns_id: str
    :param name: service name (optional, inherited from ns)
    :type name: str
    :param status: service status (optional)
    :param path: path of the service NFFG
    :type path: str
    :return: service instance
    :rtype: :any:`ServiceInstance`
    """
    # If path is missing then assembly if from ns id
    if not path:
      path = os.path.join(self.service_dir, "%s.nffg" % ns_id)
    self.log.debug("Assembled path for requested service: %s " % path)
    try:
      # Load the requested service descriptor3
      sg = NFFG.parse_from_file(path)
      self.log.debug("Service has been loaded!")
    except IOError:
      self.log.warning("NFFG file for service instance creation is not found in"
                       " %s! Skip service processing..." % self.service_dir)
      return None
    si = ServiceInstance(service_id=ns_id,
                         name=name if name else sg.name,  # Inherited from NSD
                         path=path,
                         status=status)
    self.instances[si.id] = si
    self.log.info("Add managed service: %s with instance id: %s " % (
      ns_id, si.id))
    return si

  def remove_service_instance (self, id):
    """
    Remove instance from manages services.

    :param id: service instance id
    :type id: str
    :return: None
    """
    self.log.debug("Remove service instance: %s from ServiceManager!" % id)
    if id in self.instances:
      del self.instances[id]
    else:
      self.log.warning("Service: %s is not found!" % id)

  def set_service_status (self, id, status):
    """
    Add status for service instance with given id.

    :param id: service instance id
    :type id: str
    :param status: service status
    :type status: str
    :return: None
    """
    if id not in self.instances:
      self.log.warning("Missing service instance: %s from ServiceManager!" % id)
    else:
      self.instances[id].status = status
      self.log.info("Status for service: %s updated with value: %s" %
                    (id, status))

  def get_service (self, id):
    """
    Return with information of service instance given by id.

    :param id: service instance id
    :type id: str
    :return: service description dict
    :rtype: :any:`ServiceInstance`
    """
    if id in self.instances:
      return self.instances[id]
    else:
      self.log.warning("Missing service instance: %s from ServiceManager!" % id)

  def get_service_status (self, id):
    """
    Return with status of service instance given by id.

    :param id: service id
    :type id: str
    :return: service status
    :rtype: str
    """
    if id in self.instances:
      return self.instances[id].status
    else:
      self.log.warning("Missing service instance: %s from ServiceManager!" % id)

  def get_service_name (self, id):
    """
    Return with name of service instance given by id.

    :param id: service id
    :type id: str
    :return: service name
    :rtype: str
    """
    if id in self.instances:
      return self.instances[id].name
    else:
      self.log.warning("Missing service instance: %s from ServiceManager!" % id)

  def get_running_services_status (self):
    """
    Return with the running services.

    :return: running services
    :rtype: list
    """
    self.log.info("Collect running services from ServiceManager...")
    ret = []
    for id in self.instances:
      if self.instances[id].status == ServiceInstance.STATUS_START:
        ret.append({"id": id,
                    "name": self.get_service_name(id),
                    "status": self.get_service_status(id)})
    return ret

  def get_services_status (self):
    """
    Return with the managed services.

    :return: all managed services
    :rtype: list
    """
    self.log.info("Collect managed services from ServiceManager...")
    ret = []
    for si in self.instances.itervalues():
      ret.append(si.get_json())
    return ret
