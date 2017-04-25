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
import pprint

import requests
from requests.exceptions import ConnectionError, Timeout

from colored_logger import VERBOSE


class MissingVNFDException(Exception):
  """
  Exception class signaling missing VNFD from Catalogue.
  """

  def __init__ (self, vnf_id=None):
    self.vnf_id = vnf_id

  def __str__ (self):
    return "Missing VNF id: %s from Catalogue!" % self.vnf_id


class AbstractDescriptorWrapper(object):
  """
  Abstract Wrapper class for Descriptors.
  """

  def __init__ (self, raw, logger=None):
    """
    Constructor.

    :param raw: raw data parsed from JSON file
    :type raw: dict
    :return: None
    """
    self.__data = raw
    self.__process_metadata()
    self.log = logger if logger is not None else logging.getLogger(__name__)

  @property
  def data (self):
    return self.__data

  def __str__ (self):
    return pprint.pformat(self.data)

  def __process_metadata (self):
    """
    Process common metadata.

    :return: None
    """
    self.id = self.data.get('id')
    self.name = self.data.get('name')
    self.provider = self.data.get('provider')
    self.provider_id = self.data.get('provider_id')
    self.release = self.data.get('release')
    self.description = self.data.get('description')
    self.version = self.data.get('version')
    self.descriptor_version = self.data.get('descriptor_version')


class VNFWrapper(AbstractDescriptorWrapper):
  """
  Wrapper class for VNFD data structure.
  """
  METADATA = ('bootstrap_script',  # Entry point for Docker
              'vm_image',  # Image reference
              'variables',  # Environment variables
              'networking_resources')  # Port binding

  def __init__ (self, raw):
    """
    Constructor.

    :param raw: raw data parsed from JSON file
    :type raw: dict
    :return: None
    """
    super(VNFWrapper, self).__init__(raw,
                                     logging.getLogger("VNF#%s" % raw['id']))
    self.type = self.data['type']
    self.created_at = self.data['created_at']
    self.modified_at = self.data['modified_at']
    self.vnfd_file = None

  def get_resources (self):
    """
    Get resource values: cpu, mem, storage from the single VDU in VNFD.

    :return: dict of resource values with keys cpu,mem,storage or empty tuple
    :rtype: dict
    """
    try:
      if len(self.data['vdu']) > 1:
        self.log.error(
          "Multiple VDU element are detected! Conversion does only support "
          "simple VNFs!")
        return
      res = self.data['vdu'][0]["resource_requirements"]
      return {'cpu': res['vcpus'] if 'vcpus' in res else None,
              'mem': res['memory'] if 'memory' in res else None,
              'storage': res['storage']['size']
              if 'storage' in res and 'size' in res['storage'] else None}
    except KeyError:
      self.log.error(
        "Missing required field for 'resources' in data:\n%s!" % self)
      return ()

  def get_vnf_id (self):
    """
    Get the id of the NF which comes from the single VDU id.

    :return: NF id
    :rtype: str
    """
    try:
      if len(self.data['vdu']) > 1:
        self.log.error(
          "Multiple VDU element are detected! Conversion does only support "
          "simple VNFs!")
        return
      # return self.data['vdu'][0]["alias"]
      return self.name
    except KeyError:
      self.log.error("Missing required field for 'id' in VNF: %s!" % self.id)

  def get_vnf_type (self):
    """
    Get the type of the NF which comes from the VNFD name.

    :return: NF id
    :rtype: str
    """
    try:
      if len(self.data['vdu']) > 1:
        self.log.error(
          "Multiple VDU element are detected! Conversion does only support "
          "simple VNFs!")
        return
      return self.data['vdu'][0]["alias"]
    except KeyError:
      self.log.error("Missing required field for 'type' in VNF: %s!" % self.id)

  def get_ports (self):
    """
    Get the list of defined ports of the NF, which are come from the list of
    'connection_points'.

    :return: list of the NF port ids, which are in str
    :rtype: list
    """
    try:
      if len(self.data['vdu']) > 1:
        self.log.error(
          "Multiple VDU element are detected! Conversion does only support "
          "simple VNFs!")
        return
      ports = []
      # return self.data['vdu'][0]["connection_points"]
      for cp in self.data['vdu'][0]["connection_points"]:
        ref = cp['id']
        for vlink in self.data["vlinks"]:
          if ref in vlink['connection_points_reference']:
            try:
              port_id = int(vlink['alias'])
            except ValueError:
              port_id = vlink['alias']
            ports.append(port_id)
            self.log.debug("Found VNF port: %s" % vlink['alias'])
      return ports
    except KeyError:
      self.log.error("Missing required field for 'ports' in VNF: %s!" % self.id)
      return ()

  def get_internet_ports (self):
    """
    
    :return: 
    """
    try:
      if len(self.data['vdu']) > 1:
        self.log.error(
          "Multiple VDU element are detected! Conversion does only support "
          "simple VNFs!")
        return
      ports = []
      for vlink in self.data["vlinks"]:
          if str(vlink['connectivity_type']).upper() == 'INTERNET':
            try:
              port_id = int(vlink['alias'])
            except ValueError:
              port_id = vlink['alias']
            ports.append(port_id)
            self.log.debug("Detected INTERNET port: %s" % vlink['alias'])
      return ports
    except KeyError:
      self.log.error("Missing required field for 'ports' in VNF: %s!" % self.id)
      return ()

  def get_deployment_type (self):
    """
    Get the deployment_type value which come from the 'deployment_flavours'
    entry.

    :return: deployment_type
    :rtype: str
    """
    try:
      for deployment in self.data['deployment_flavours']:
        if deployment['id'] == "deployment_type":
          return deployment['constraint'] if deployment['constraint'] else None
    except KeyError:
      self.log.error(
        "Missing required field for 'deployment_type' in VNF: %s!" % self.id)

  def get_metadata (self):
    """
    Return with additional data defined for VNF.
    
    :return: dict of metadata
    :rtype: dict
    """
    rv = {}
    try:
      for md in self.METADATA:
        if md in self.data['vdu'][0]:
          rv[md] = self.data['vdu'][0][md]
      return rv
    except KeyError as e:
      self.log.error(
        "Missing required field for metadata: %s in VNF: %s!" % (e.message,
                                                                 self.id))


class VNFCatalogue(object):
  """
  Container class for VNFDs.
  """
  LOGGER_NAME = "VNFCatalogue"
  VNF_CATALOGUE_DIR = "vnf_catalogue"
  VNF_STORE_ENABLED = False
  STORE_VNFD_LOCALLY = True
  REQUEST_TIMEOUT = 1

  def __init__ (self, use_remote=False, vnf_store_url=None, cache_dir=None,
                logger=None):
    """
    Constructor.

    :param logger: optional logger
    """
    if logger is not None:
      self.log = logger.getChild(self.LOGGER_NAME)
      # self.log.name = self.LOGGER_NAME
    else:
      logging.getLogger(self.__class__.__name__)
    self.__catalogue = {}
    if cache_dir:
      self.VNF_CATALOGUE_DIR = cache_dir
    self.log.debug("Use directory for VNF cache: %s" % self.VNF_CATALOGUE_DIR)
    self.vnf_store_url = vnf_store_url
    if use_remote:
      self.VNF_STORE_ENABLED = True
      self.log.debug("Set VNF Store with URL: %s" % self.vnf_store_url)
    else:
      self.log.debug("Using VNF Store is disabled!")

  def initialize (self):
    """
    Initialize VNFCatalogue by reading cached VNFDs from file.
    
    :return: None
    """
    self.log.info("Initialize %s..." % self.__class__.__name__)
    self.parse_vnf_catalogue_from_folder()

  def __str__ (self):
    """
    Return with string representation.

    :return: string representation
    :rtype: str
    """
    return "%s(dir: %s, URL:%s, enabled_remote: %s)" % (
      self.__class__.__name__, self.VNF_CATALOGUE_DIR, self.vnf_store_url,
      self.VNF_STORE_ENABLED)

  def register (self, id, vnfd):
    """
    Add a VNF as a VNFWrapper class with the given name.
    Return if the registering was successful.

    :param id: id of the VNF
    :type id: str
    :param vnfd: VNFD as a :any:`VNFWrapper` class
    :type vnfd: VNFWrapper
    :return: result of registering
    :rtype: bool
    """
    if isinstance(vnfd, VNFWrapper):
      if id not in self.__catalogue:
        self.__catalogue[id] = vnfd
        self.log.debug("Register VNFD with id: %s" % id)
      else:
        self.log.debug("VNFD has been already registered with id: %s!" % id)
      return True
    else:
      return False

  def unregister (self, id):
    """
    Remove a VNF from the catalogue given by name.

    :param id: removed VNF
    :type id: str
    :return: None
    """
    del self.__catalogue[id]
    self.log.debug(
      "VNFD with id: %s is removed from %s" % (id, self.__class__.__name__))

  def registered (self, id):
    return id in self.__catalogue

  def get_registered_vnfs (self):
    return self.__catalogue.keys()

  def get_by_id (self, id):
    """
    Return a registered VNF as a VNFWrapper given by the VNF id.

    :param id: VNF id
    :type id: str
    :return: registered VNF or None
    :rtype: VNFWrapper
    """
    if self.VNF_STORE_ENABLED:
      return self.request_vnf_from_remote_store(id)
    for vnf in self.__catalogue.itervalues():
      if vnf.id == id:
        return vnf

  def parse_vnf_catalogue_from_folder (self, catalogue_dir=None):
    """
    Parse the given VNFDs as :any:`VNFWrapper` from files under the
    directory given by 'catalogue_dir' into a :any:`VNFCatalogue` instance.
    catalogue_dir can be relative to $PWD.

    :param catalogue_dir: VNF folder
    :type catalogue_dir: str
    :return: created VNFCatalogue instance
    :rtype: VNFCatalogue
    """
    self.log.debug(
      "Parse VNFDs from local folder: %s ..." % self.VNF_CATALOGUE_DIR)
    # Iterate over catalogue dir
    for vnf in os.listdir(self.VNF_CATALOGUE_DIR):
      if vnf.startswith('.'):
        continue
      vnfd_file = os.path.join(self.VNF_CATALOGUE_DIR, vnf)
      with open(vnfd_file) as f:
        # Parse VNFD from JSOn files as VNFWrapper class
        vnfd = json.load(f, object_hook=self.__vnfd_object_hook)
        vnfd.vnfd_file = vnfd_file
        vnfd_id = os.path.splitext(vnf)[0]
        if not self.registered(id=vnfd_id):
          # Register VNF into catalogue
          self.register(id=vnfd_id, vnfd=vnfd)
    return self

  def request_vnf_from_remote_store (self, vnf_id):
    """
    Request a VNFD given by vnf_id from remote VNFStore.

    :param vnf_id: VNF id
    :type vnf_id: str
    :return: parsed VNFD if it's found else None
    :rtype: VNFWrapper
    """
    if all((self.VNF_STORE_ENABLED, self.STORE_VNFD_LOCALLY,
            vnf_id in self.__catalogue)):
      self.log.debug("Return with cached VNFD(id: %s)" % vnf_id)
      return self.__catalogue[vnf_id]
    self.log.debug("Request VNFD with id: %s from VNF Store..." % vnf_id)
    if not self.vnf_store_url:
      self.log.error("Missing VNF Store URL from %s" % self.__class__.__name__)
      return
    url = os.path.join(self.vnf_store_url, str(vnf_id))
    self.log.debug("Used URL for VNFD request: %s" % url)
    try:
      response = requests.get(url=url,
                              timeout=self.REQUEST_TIMEOUT)
    except Timeout:
      self.log.error(
        "Request timeout: %ss exceeded! VNF Store: %s is unreachable!" % (
          self.REQUEST_TIMEOUT, self.vnf_store_url))
      raise MissingVNFDException(vnf_id=vnf_id)
    except ConnectionError as e:
      self.log.error(str(e))
      raise MissingVNFDException(vnf_id=vnf_id)
    if not response.ok:
      if response.status_code == httplib.NOT_FOUND:  # HTTP 404
        self.log.warning(
          "Got HTTP 404! VNFD (id: %s) is missing from VNF Store!" % vnf_id)
      else:
        self.log.error("Got error during requesting VNFD with id: %s!" % vnf_id)
      return
    self.log.log(VERBOSE,
                 "Received body:\n%s" % pprint.pformat(response.json()))
    vnfd = json.loads(response.text, object_hook=self.__vnfd_object_hook)
    if self.STORE_VNFD_LOCALLY:
      self.register(id=vnf_id, vnfd=vnfd)
    return vnfd

  @staticmethod
  def __vnfd_object_hook (obj):
    """
    Object hook function for converting top dict into :any:`VNFWrapper`
    instance.
    """
    return VNFWrapper(raw=obj) if 'vdu' in obj.keys() else obj

  # Container-like magic functions

  def iteritems (self):
    return self.__catalogue.iteritems()

  def __getitem__ (self, item):
    return self.__catalogue[item]

  def __iter__ (self):
    return self.__catalogue.__iter__()
