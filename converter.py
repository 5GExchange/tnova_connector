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
    self.log = logger if logger is not None else logging.getLogger(__name__)

  @property
  def data (self):
    return self.__data

  def __str__ (self):
    return pprint.pformat(self.data)

  def __process_metadata (self):
    self.id = self.data['id']
    self.name = self.data['name']
    self.provider = self.data['provider']
    self.provider_id = self.data['provider_id']
    self.release = self.data['release']
    self.description = self.data['description']
    self.version = self.data['version']
    self.descriptor_version = self.data['descriptor_version']
    self.created_at = self.data['created_at']
    self.modified_at = self.data['modified_at']


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
    super(VNFWrapper, self).__init__(raw)
    self.type = self.data['type']

  def get_resources (self):
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

  def get_id (self):
    try:
      if len(self.data['vdu']) > 1:
        self.log.error(
          "Multiple VDU element are detected! Conversion does only support "
          "simple VNFs!")
        return
      return self.data['vdu'][0]["id"]
    except KeyError:
      self.log.error("Missing required field for 'id' in data:\n%s!" % self)

  def get_ports (self):
    try:
      if len(self.data['vdu']) > 1:
        self.log.error(
          "Multiple VDU element are detected! Conversion does only support "
          "simple VNFs!")
        return
      return self.data['vdu']["connection_points"]
    except KeyError:
      self.log.error("Missing required field for 'ports' in data:\n%s!" % self)

  def get_deployment_type (self):
    try:
      for deployment in self.data['deployment_flavours']:
        if deployment['id'] == "deployment_type":
          return deployment['constraint']
    except KeyError:
      self.log.error("Missing required field for 'ports' in data:\n%s!" % self)


class NSWrapper(AbstractDescriptorWrapper):
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
    super(NSWrapper, self).__init__(raw)


class VNFCatalogue(object):
  """
  Container class for VNFDs.
  """

  def __init__ (self):
    self.catalogue = {}

  def register (self, name, data):
    self.catalogue[name] = data

  def iteritems (self):
    return self.catalogue.iteritems()

  def __getitem__ (self, item):
    return self.catalogue[item]

  def __iter__ (self):
    return self.catalogue.__iter__()


class TNOVAConverter(object):
  """
  Converter class for NSD --> NFFG conversion.
  """
  VNF_CATALOGUE = "vnf_catalogue"

  def __init__ (self, logger=None):
    self.log = logger if logger is not None else logging.getLogger(__name__)

  def _parse_vnf_catalogue (self, catalogue_dir=None):
    if catalogue_dir is None:
      catalogue_dir = os.path.realpath(
        os.path.join(os.path.dirname(__file__), self.VNF_CATALOGUE))
      vnf_catalogue = VNFCatalogue()
      for vnf in os.listdir(catalogue_dir):
        with open(os.path.join(catalogue_dir, vnf)) as f:
          vnfd = json.load(f, object_hook=self.__vnfd_object_hook)
          vnf_catalogue.register(name=vnf.rstrip(".json"), data=vnfd)
      return vnf_catalogue

  @staticmethod
  def __vnfd_object_hook (obj):
    return VNFWrapper(raw=obj) if 'vdu' in obj.keys() else obj

  def _parse_nsd (self, nsd_file):
    print nsd_file
    with open(os.path.abspath(nsd_file)) as f:
      return json.load(f, object_hook=self.__nsd_object_hook)

  @staticmethod
  def __nsd_object_hook (obj):
    return NSWrapper(raw=obj['nsd']) if 'nsd' in obj else obj

  def convert (self, nsd_file):
    self.log.info("Parse Network Service (NS) from NSD file: %s" % nsd_file)
    ns = self._parse_nsd(nsd_file)
    self.log.info("Parse VNFs from VNFD files under: %s" % self.VNF_CATALOGUE)
    vnfs = self._parse_vnf_catalogue()
    self.log.debug("Registered VNFs: %s" % vnfs.catalogue.keys())


if __name__ == "__main__":
  logging.basicConfig(level=logging.DEBUG)
  converter = TNOVAConverter()
  # catalogue = converter._parse_vnf_catalogue()
  # for i, vnf in catalogue.iteritems():
  #   print i, vnf
  # print converter._parse_nsd("escape-mn-req.json")
  converter.convert("escape-mn-req.json")
