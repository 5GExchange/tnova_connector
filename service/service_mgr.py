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
import ast
import datetime
import httplib
import json
import logging
import os
import pprint
import uuid

import requests
from requests import Timeout
from requests.exceptions import ConnectionError

from conversion.vnf_catalogue import MissingVNFDException
from nffg_lib.nffg import NFFG
from util.colored_logger import VERBOSE
from virtualizer.virtualizer import Virtualizer


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
                status=STATUS_INIT):
    """
    Init service instance.
    
    :param service_id: service id
    :type service_id: str
    :param instance_id: unique instance id
    :type instance_id: str
    :param name: service name
    :type name: str
    :param path: path of cached service file
    :type path: str
    :param status: service status
    :type status: str 
    """
    self.id = instance_id if instance_id else str(uuid.uuid1())
    self.service_id = service_id  # Converted NFFG the service created from
    # The id of the service instance
    self.sg = None
    self.name = name
    self.path = path
    self.__status = status
    self.vnf_addresses = {}
    self.created_at = self.__touch()
    self.updated_at = self.__touch()
    self.__nf_id_binding = {}

  @staticmethod
  def __touch ():
    """
    Update the updated_at attribute.

    :return: new value
    :rtype: str
    """
    return datetime.datetime.now().isoformat()

  @property
  def status (self):
    return self.__status

  @status.setter
  def status (self, value):
    self.__status = value
    self.__touch()

  @property
  def get_sg (self):
    return self.sg

  @property
  def binding (self):
    return self.__nf_id_binding

  def get_json (self):
    """
    Return the service instance in JSON format.

    :return: service instance description is JSON
    :rtype: dict
    """
    return {"id": self.id,
            "ns-id": self.service_id,
            "name": self.name,
            "status": self.__status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "vnf_addresses": self.vnf_addresses}

  def load_sg_from_file (self, path=None, mode=None):
    """
    Read and return the service description this service instance originated
    from.

    :param path: overrided path (optional)
    :type path: str
    :param mode: optional mapping mode
    :type mode: str
    :return: read NFFG
    :rtype: NFFG
    """
    if path is None:
      path = self.path
    # Load NFFG from file
    try:
      nffg = NFFG.parse_from_file(path=path)
      # Rewrite the default SG id to the instance id to be unique for ESCAPE
      if nffg.service_id is None:
        nffg.service_id = nffg.id
      nffg.id = self.id
      if mode is not None:
        nffg.mode = mode
      self.sg = self._tag_NF_ids(nffg=nffg, unique=self.id)
      return self.sg
    except IOError:
      # return None
      raise

  def _tag_NF_ids (self, nffg, unique):
    """
    Modify NF ids with given `unique` tag and handle SG hops as well.
     
    :param nffg: NFFG object
    :type nffg: :class:``
    :param unique: 
    :return: 
    """
    self.__nf_id_binding.update({nf.id: "%s_%s" % (nf.id, unique)
                                 for nf in nffg.nfs})
    raw = nffg.dump()
    for old, new in self.__nf_id_binding.iteritems():
      # decompressor_0 id contains the compressor_0 id --> use trick to consider
      # the string apostrophe as well
      raw = raw.replace('"%s"' % old, '"%s"' % new)
    return NFFG.parse(raw_data=raw)


class ServiceManager(object):
  """
  Manager class for NSD instances.
  Very primitive.
  """
  LOGGER_NAME = "ServiceManager"
  # Default ESCAPE URL
  RO_URL = "http://localhost:8008"
  # Default NSD cache
  NSD_DIR = "nsds"
  # Default Service Catalog attributes
  SERVICE_DIR = "services"
  SERVICE_CATALOG_ENABLED = False
  REQUEST_TIMEOUT = 3

  def __init__ (self, converter, use_remote=False, service_catalog_url=None,
                cache_dir=None, nsd_dir=None, logger=None):
    """
    Init Service Manager.
    
    :param converter: used Converter object
    :type converter: :class:`TNOVAConverter`
    :param use_remote: enable remote service catalog
    :type use_remote: bool
    :param service_catalog_url: service catalog URL
    :type service_catalog_url: str
    :param cache_dir: directory path of cached servcie files
    :type cache_dir: str
    :param nsd_dir: directory path of cached NSD files
    :type nsd_dir: str
    :param logger: optional logger object
    :type logger: :class:`logging.Logger`
    """
    if logger is not None:
      self.log = logger.getChild(self.LOGGER_NAME)
    else:
      logging.getLogger(self.__class__.__name__)
    # service-id: ServiceInstance object
    self.converter = converter
    self.log.debug("Using converter: %s" % self.converter)
    self.__instances = {}
    # Store NF id --> ServiceInstance id
    self.__vnf_cache = {}
    if nsd_dir:
      self.NSD_DIR = nsd_dir
    self.log.debug("Use directory for NSD cache: %s" % self.NSD_DIR)
    if cache_dir:
      self.SERVICE_DIR = cache_dir
    self.log.debug("Use directory for service cache: %s" % self.SERVICE_DIR)
    self.service_catalog_url = service_catalog_url
    if use_remote:
      self.SERVICE_CATALOG_ENABLED = True
      self.log.debug(
        "Set Service Catalog with URL: %s" % self.service_catalog_url)
    else:
      self.log.info("Using Service Catalog is disabled!")

  def initialize (self):
    """
    Initialize NSDManager from persistent files.

    :return: None
    """
    self.log.info("Initialize %s..." % self.__class__.__name__)
    self.log.debug("Read defined services from location: %s" % self.SERVICE_DIR)
    for filename in os.listdir(self.SERVICE_DIR):
      if not filename.startswith('.') and filename.endswith('.nffg'):
        service_id = os.path.splitext(filename)[0]
        self.log.debug("Detected cached service NFFG: %s" % service_id)

  def store_nsd (self, raw):
    """
    Parse the given raw NSD string and store it into a file.
    Returns with the file path.

    :param raw: raw NSD data in JSON
    :type raw: str
    :return: cache file path
    :rtype: str
    """
    try:
      # Parse data as JSON
      self.log.debug("Parsing NSD body...")
      data = json.loads(raw)
      self.log.log(VERBOSE, "Parsed body:\n%s" % pprint.pformat(data))
      # Filename based on the service ID
      filename = data['nsd']['id']
      path = os.path.realpath(os.path.join(self.NSD_DIR, "%s.json" % filename))
      # Write into file
      with open(path, 'w') as f:
        f.write(json.dumps(data, indent=2, sort_keys=True))
        self.log.info("Received NSD has been saved into %s!" % path)
      return path
    except ValueError:
      self.log.exception("Received data is not valid JSON!")
      self.log.debug("Received body:\n%s" % raw)
      return
    except KeyError:
      self.log.exception("Received data is not valid NSD!")
      self.log.debug("Received body:\n%s" % raw)
      return
    except MissingVNFDException:
      self.log.exception("Unrecognisable VNFD has been found in NSD!")
      raise
    except:
      self.log.exception(
        "Got unexpected exception during NSD -> NFFG conversion!")
      raise

  def instantiate_ns (self, ns_id, path=None, name=None):
    """
    Create a service (NS) instance with optional status.

    :param ns_id: service id
    :type ns_id: str
    :param name: service name (optional, inherited from ns)
    :type name: str
    :param path: path of the service NFFG
    :type path: str
    :return: service instance
    :rtype: ServiceInstance
    """
    # If path is missing then assembly if from ns_id
    if not path:
      path = os.path.join(self.SERVICE_DIR, "%s.nffg" % ns_id)
    # Create Service Instance trunk
    si = ServiceInstance(service_id=ns_id, name=name, path=path)
    self.log.debug("Assembled path for requested service: %s " % path)
    if not os.path.exists(path=path):
      self.log.warning("Service with id: %s is not found in cache dir: %s!"
                       % (ns_id, self.SERVICE_DIR))
      # Search for cached NSD and convert it on-the-fly
      nsd_path = os.path.join(self.NSD_DIR, "%s.json" % ns_id)
      self.log.debug("Trying to convert service from NSD: %s..." % nsd_path)
      if not os.path.exists(path=nsd_path):
        self.log.warning("NSD with id: %s is not found in cache dir: %s!"
                         % (ns_id, self.NSD_DIR))
        if self.SERVICE_CATALOG_ENABLED:
          # Try to acquire the NSD from remote service catalog and convert it
          nsd_path = self.request_nsd_from_remote_store(ns_id=ns_id)
          if not nsd_path:
            self.log.error("Failed to acquire NSD: %s" % ns_id)
            si.status = si.STATUS_ERROR
            return si
        else:
          self.log.warning("Using service-catalog is disabled!")
          return
      # Convert the NSD given by file name
      sg = self.convert_service(nsd_file=nsd_path)
      self.log.info("NSD conversion has been ended!")
      if sg is None:
        self.log.error("Service conversion was failed! Service is not saved!")
        si.status = si.STATUS_ERROR
        return si
    try:
      self.log.debug("Loading Service Descriptor from file...")
      # Load the requested service descriptor
      sg = si.load_sg_from_file()
      self.log.debug("Service has been loaded!")
    except IOError:
      self.log.warning("NFFG file for service instance creation is not found "
                       "in %s! Skip service processing..." % self.SERVICE_DIR)
      si.status = si.STATUS_ERROR
      return si
    # Update Service Instance
    si.name = name if name else sg.name  # Inherited from NSD
    si.path = path
    si.status = ServiceInstance.STATUS_INIT
    # Store Service Instance
    self.__instances[si.id] = si
    self.__update_vnf_cache(data=sg, si_id=si.id)
    self.log.info("Add managed service: %s with instance id: %s " % (ns_id,
                                                                     si.id))
    return si

  def __update_vnf_cache (self, data, si_id):
    if isinstance(data, NFFG):
      self.__vnf_cache.update(((nf.id, si_id) for nf in data.nfs))
      self.log.debug("Updated VNF cache: %s" % self.__vnf_cache)

  def request_nsd_from_remote_store (self, ns_id):
    """
    
    :param ns_id: 
    :return: path
    """
    self.log.debug("Fetching NSD: %s from service-catalog: %s"
                   % (ns_id, self.service_catalog_url))
    if not self.service_catalog_url:
      self.log.error("Missing Service Catalog URL from %s"
                     % self.__class__.__name__)
      return
    url = os.path.join(self.service_catalog_url, str(ns_id))
    self.log.debug("Used URL for NSD request: %s" % url)
    try:
      response = requests.get(url=url,
                              timeout=self.REQUEST_TIMEOUT)
    except Timeout:
      self.log.error("Request timeout: %ss exceeded! Service Catalog: %s is "
                     "unreachable!" % (self.REQUEST_TIMEOUT,
                                       self.service_catalog_url))
      return
    except ConnectionError as e:
      self.log.error(str(e))
      return
    if not response.ok:
      if response.status_code == httplib.NOT_FOUND:
        self.log.warning("Got %s! NSD (id: %s) is missing from Service Catalog!"
                         % (httplib.NOT_FOUND, ns_id))
      else:
        self.log.error("Got error during requesting NSD with id: %s!" % ns_id)
      return
    self.log.info("NSD: %s has been acquired from Service Catalog: %s" %
                  (ns_id, self.service_catalog_url))
    self.log.log(VERBOSE, "Received body:\n%s" % pprint.pformat(response.json))
    return self.store_nsd(raw=response.text)

  def convert_service (self, nsd_file):
    """
    Perform the conversion of the received NSD and save the NFFG.

    :param nsd_file: path of the stored NSD file
    :type nsd_file: str
    :return: converted NFFG
    :rtype: :class:`NFFG`
    """
    self.log.info("Start converting received NSD...")
    # Convert the NSD given by file name
    sg = self.converter.convert(nsd_file=nsd_file)
    self.log.info("NSD conversion has been ended!")
    if sg is None:
      self.log.error("Service conversion was failed! Service is not saved!")
      return
    self.log.log(VERBOSE, "Converted service:\n%s" % sg.dump())
    # Save result NFFG into a file
    sg_path = os.path.join(self.SERVICE_DIR, "%s.nffg" % sg.id)
    with open(sg_path, 'w') as f:
      f.write(sg.dump())
      self.log.info("Converted NFFG has been saved! Path: %s" % sg_path)
    return sg

  def remove_service_instance (self, id):
    """
    Remove instance from manages services.

    :param id: service instance id
    :type id: str
    :return: terminated service instance
    :rtype: ServiceInstance
    """
    self.log.debug("Remove service instance: %s from ServiceManager!" % id)
    if id in self.__instances:
      si = self.get_service(id=id)
      del self.__instances[id]
      si.status = ServiceInstance.STATUS_STOPPED
      return si
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
    if id not in self.__instances:
      self.log.warning("Missing service instance: %s from ServiceManager!" % id)
    else:
      self.__instances[id].status = status
      self.log.info("Status for service: %s updated with value: %s" %
                    (id, status))

  def get_service (self, id):
    """
    Return with information of service instance given by id.

    :param id: service instance id
    :type id: str
    :return: service instance object
    :rtype: ServiceInstance
    """
    if id in self.__instances:
      return self.__instances[id]
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
    if id in self.__instances:
      return self.__instances[id].status
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
    if id in self.__instances:
      return self.__instances[id].name
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
    for si in self.__instances.itervalues():
      if si.status == ServiceInstance.STATUS_START:
        ret.append(si.get_json())
    return ret

  def get_services_status (self):
    """
    Return with the managed services.

    :return: all managed services
    :rtype: list
    """
    self.log.info("Collect managed services from ServiceManager...")
    ret = []
    for si in self.__instances.itervalues():
      ret.append(si.get_json())
    return ret

  def update_si_addresses_from_ro (self, topo):
    """
    
    :param topo: 
    :return: 
    """
    self.log.debug("Collect IP addresses from received topology...")
    if isinstance(topo, NFFG):
      vnf_address = self.__collect_addr_from_nffg(nffg=topo)
    elif isinstance(topo, Virtualizer):
      vnf_address = self.__collect_addr_from_virtualizer(virt=topo)
    else:
      self.log.error("Unrecognized topology format: %s" % type(topo))
      return
    self.log.debug("Collected IP info:\n%s" % pprint.pformat(vnf_address))
    # Update SI based on collected NF<->IPs
    for vnf_id, ip in vnf_address.iteritems():
      if vnf_id not in self.__vnf_cache:
        self.log.warning("VNF: %s is missing from cache!" % vnf_id)
        continue
      si = self.get_service(id=self.__vnf_cache[vnf_id])
      if si.status != ServiceInstance.STATUS_START:
        self.log.debug("Service Instance: %s is not started. "
                       "Skip IP address update..." % si.id)
        continue
      si.vnf_addresses.update({vnf_id: ip})
      self.log.debug("Updated IP: %s ---> %s" % (vnf_id, ip))

  @staticmethod
  def __collect_addr_from_nffg (nffg):
    """
    
    :param nffg: 
    :return: 
    """
    collected = {}
    for nf in nffg.nfs:
      for port in nf.ports:
        if port.l4:
          try:
            binding = ast.literal_eval(port.l4)
            for k, v in binding.iteritems():
              # k ~ 'tcp/22'
              # v ~ ('192.168.0.1', '22')
              ips = ":".join([str(e) for e in v])
              if nf.id not in collected:
                collected[nf.id] = {"port-%s" % k: ips}
              else:
                collected[nf.id]["port-%s" % k] = ips
          except (ValueError, KeyError):
            pass
        for l3 in port.l3:
          if l3.provided is not None:
            key = "%s-%s" % (l3.id, port.id)
            if nf.id not in collected:
              collected[nf.id] = {key: l3.provided}
            else:
              collected[nf.id][key] = l3.provided
    return collected

  @staticmethod
  def __collect_addr_from_virtualizer (virt):
    """
    
    :param virt: 
    :return: 
    """
    collected = {}
    for node in virt.nodes:
      for nf in node.NF_instances:
        for port in nf.ports:
          if port.addresses.l4.is_initialized():
            try:
              binding = ast.literal_eval(port.addresses.l4.get_value())
              for k, v in binding.iteritems():
                # k ~ tcp/22
                # v ~ ('192.168.0.1', '22')
                print k, v
                ips = ":".join([str(e) for e in v])
                if nf.id.get_value() not in collected:
                  collected[nf.id.get_value()] = {"port-%s" % k: ips}
                else:
                  collected[nf.id.get_value()]["port-%s" % k] = ips
            except (ValueError, KeyError):
              pass
          for l3 in port.addresses:
            if l3.provided.is_initialized():
              key = "%s-%s" % (l3.id.get_value(), port.id.get_value())
              if nf.id.get_value() not in collected:
                collected[nf.id.get_value()] = {key: l3.provided.get_value()}
              else:
                collected[nf.id.get_value()][key] = l3.provided.get_value()
    return collected
