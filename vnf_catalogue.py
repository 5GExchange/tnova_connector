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
import logging
import os
import pprint
import sys

import requests
from requests.exceptions import ConnectionError, Timeout

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
            ports.append(vlink['alias'])
            self.log.debug("Found VNF port: %s" % vlink['alias'])
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


class VNFCatalogue(object):
  """
  Container class for VNFDs.
  """
  LOGGER_NAME = "VNFCatalogue"
  # VNF_STORE_ENABLED = False
  VNF_CATALOGUE_DIR = "vnf_catalogue"
  VNF_STORE_ENABLED = True
  STORE_VNFD_LOCALLY = True
  REQUEST_TIMEOUT = 1

  def __init__ (self, remote_store=False, url=None, catalogue_dir=None,
                logger=None):
    """
    Constructor.

    :param logger: optional logger
    """
    if logger is not None:
      self.log = logger.getChild(self.LOGGER_NAME)
      self.log.name = self.LOGGER_NAME
    else:
      logging.getLogger(self.__class__.__name__)
    self.catalogue = {}
    if catalogue_dir:
      self.VNF_CATALOGUE_DIR = catalogue_dir
    if remote_store:
      self.VNF_STORE_ENABLED = True
    self.vnf_store_url = url
    self._full_catalogue_path = None

  def register (self, id, vnfd):
    """
    Add a VNF as a VNFWrapper class with the given name.
    Return if the registering was successful.

    :param id: id of the VNF
    :type id: str
    :param vnfd: VNFD as a :any:`VNFWrapper` class
    :return: result of registering
    :rtype: bool
    """
    if isinstance(vnfd, VNFWrapper):
      if id not in self.catalogue:
        self.catalogue[id] = vnfd
        self.log.info("Register VNFD with id: %s" % id)
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
    del self.catalogue[id]
    self.log.info(
      "VNFD with id: %s is removed from %s" % (id, self.__class__.__name__))

  def get_by_id (self, id):
    """
    Return a registered VNF as a VNFWrapper given by the VNF id.

    :param id: VNF id
    :type id: str
    :return: registered VNF or None
    :rtype: :any:`VNFWrapper`
    """
    if self.VNF_STORE_ENABLED:
      return self.request_vnf_from_remote_store(id)
    for vnf in self.catalogue.itervalues():
      if vnf.id == id:
        return vnf

  def parse_vnf_catalogue_from_folder (self, catalogue_dir=None):
    """
    Parse the given VNFDs as :any:`VNFWrapper` from files under the
    directory
    given by 'catalogue_dir' into a :any:`VNFCatalogue` instance.
    catalogue_dir can be relative to $PWD.

    :param catalogue_dir: VNF folder
    :type catalogue_dir: str
    :return: created VNFCatalogue instance
    :rtype: :any:`VNFCatalogue`
    """
    if catalogue_dir is None:
      catalogue_dir = os.path.realpath(
        os.path.join(os.path.dirname(__file__), self.VNF_CATALOGUE_DIR))
      self._full_catalogue_path = catalogue_dir
    self.log.debug(
      "Parse VNFDs from local folder: %s ..." % self._full_catalogue_path)
    # Iterate over catalogue dir
    for vnf in os.listdir(self._full_catalogue_path):
      if vnf.startswith('.'):
        continue
      vnfd_file = os.path.join(catalogue_dir, vnf)
      with open(vnfd_file) as f:
        # Parse VNFD from JSOn files as VNFWrapper class
        vnfd = json.load(f, object_hook=self.__vnfd_object_hook)
        vnfd.vnfd_file = vnfd_file
        # Register VNF into catalogue
        self.register(id=os.path.splitext(vnf)[0], vnfd=vnfd)
    return self

  def request_vnf_from_remote_store (self, vnf_id):
    if all((self.VNF_STORE_ENABLED, self.STORE_VNFD_LOCALLY,
            vnf_id in self.catalogue)):
      self.log.debug("Return with cached VNFD(id: %s)" % vnf_id)
      return self.catalogue[vnf_id]
    self.log.debug("Request VNFD with id: %s from VNF Store..." % vnf_id)
    if not self.vnf_store_url:
      self.log.error("Missing VNF Store URL from %s" % self.__class__.__name__)
      return
    url = os.path.join(self.vnf_store_url, str(vnf_id))
    self.log.debug("Used URL for VNFD request: %s" % url)
    try:
      response = requests.get(url=os.path.join(self.vnf_store_url, str(vnf_id)),
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
      if response.status_code == 404:
        self.log.debug(
          "Got HTTP 404! VNFD (id: %s) is missing from VNF Store!" % vnf_id)
      else:
        self.log.error("Got error during requesting VNFD with id: %s!" % vnf_id)
      return None
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
    return self.catalogue.iteritems()

  def __getitem__ (self, item):
    return self.catalogue[item]

  def __iter__ (self):
    return self.catalogue.__iter__()
