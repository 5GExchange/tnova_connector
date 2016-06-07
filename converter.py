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
import json
import logging
import os
import pprint
import sys

import requests

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


class NSWrapper(AbstractDescriptorWrapper):
  """
  Wrapper class for VNFD data structure.
  """
  # Constants
  LINK_TYPE = "E-LINE"

  def __init__ (self, raw):
    """
    Constructor.

    :param raw: raw data parsed from JSON file
    :type raw: dict
    :return: None
    """
    super(NSWrapper, self).__init__(raw, logging.getLogger("NS#%s" % raw['id']))
    self.vendor = self.data.get('vendor')

  def get_vnfs (self):
    """
    Get the used VNF id converted to int from the 'vnfds' list.

    :return: VNF ids
    :rtype: list
    """
    try:
      return [int(vnf) for vnf in self.data['vnfds']]
    except KeyError:
      self.log.error("Missing required field for 'vnfds' in NSD: %s!" % self.id)
    except ValueError as e:
      self.log.error("Listed VNF id in 'vnfds': %s is not a valid integer!" % e)

  def get_saps (self):
    """
    Get the list of SAPs wich come from the 'connection_points' klist.

    :return: SAP ids
    :rtype: list
    """
    try:
      # return self.data['connection_points']
      # return self.data['connection_points']
      saps = []
      for cp in self.data['vnffgd']['vnffgs'][0]['network_forwarding_path'][0][
        'connection_points']:
        if cp.startswith('ns_ext'):
          ext_point = cp.lstrip('ns_ext_')
          if ext_point not in saps:
            saps.append(ext_point)
            self.log.debug("Found SAP: %s" % ext_point)
      return saps
    except KeyError:
      self.log.error(
        "Missing required field for SAPs in 'connection_points' in NSD: %s!" %
        self.id)

  def __parse_vlink_connection (self, conn):
    if conn.startswith('VNF#'):
      parts = conn.split(':')
      return int(parts[0].lstrip('VNF#')), parts[1].lstrip('ext_')
    else:
      self.log.error("Missing VNF prefix from connection: %s" % conn)

  def get_vlinks (self):
    """
    Get the list of processed Virtual links.
    The returned structure contains the link id and the source/destination
    endpoints separated into node/port ids.
    The node and port ids are splitted and converted to int if it was a number.

    :return: list of dicts which contains virtual link parameters
    :rtype: list
    """
    try:
      hops = []
      for vlink in self.data['vld']['virtual_links']:
        if vlink['connectivity_type'] != self.LINK_TYPE:
          self.log.warning(
            "Only Link type: %s is supported! Skip Virtual link "
            "processing:\n%s" % (self.LINK_TYPE, vlink))
          continue
        hop = {}
        try:
          hop['id'] = int(vlink['vld_id'])
        except ValueError:
          hop['id'] = vlink['vld_id']
        # Inter-VNF link
        if len(vlink['connections']) == 2:
          self.log.debug("Detected inter-VNF link: %s" % hop['id'])
          # Check src node/port
          hop['src_node'], hop['src_port'] = self.__parse_vlink_connection(
            vlink['connections'][0])
          # Check dst node/port
          hop['dst_node'], hop['dst_port'] = self.__parse_vlink_connection(
            vlink['connections'][1])
        # External link, one of the endpoint is a SAP
        else:
          node, port = self.__parse_vlink_connection(vlink['connections'][0])
          sap_node, sap_port = vlink['alias'], None
          # Try to detect SAP role
          cp_list = self.data['vnffgd']['vnffgs'][0][
            'network_forwarding_path'][0]['connection_points']
          graph_list = self.data['vnffgd']['vnffgs'][0][
            'network_forwarding_path'][0]['graph']
          # pos = cp_list.index(vlink['connections'][0])
          pos = graph_list.index(vlink['vld_id']) * 2 + 1
          # pos should be 1, 3, 5, ...
          if pos < 2:
            # First link of the chain started from the SAP
            hop['src_node'], hop['src_port'] = sap_node, sap_port
            hop['dst_node'], hop['dst_port'] = node, port
            self.log.debug("Detected starting SAP")
          elif cp_list[pos - 2] == vlink['connections'][0]:
            # Destination endpoint of the previous link is the same as the
            # current endpoint => link directed to the SAP
            hop['src_node'], hop['src_port'] = node, port
            hop['dst_node'], hop['dst_port'] = sap_node, sap_port
            self.log.debug("Detected ending SAP")
          else:
            # not the same => it is the first link of a new chain
            hop['src_node'], hop['src_port'] = sap_node, sap_port
            hop['dst_node'], hop['dst_port'] = node, port
            self.log.debug("Detected starting SAP of a new service chain")
        self.log.debug("src: %s - %s" % (hop['src_node'], hop['src_port']))
        self.log.debug("dst: %s - %s" % (hop['dst_node'], hop['dst_port']))
        hops.append(hop)
      return hops
    except KeyError:
      self.log.error("Missing required field for 'vld' in data:\n%s!" % self)

  def get_e2e_reqs (self):
    """
    Get list of E2E requirement link params: id, delay, bandwidth which come
    from 'sla' fields.

    :return: list of requirement link params
    :rtype: list
    """
    try:
      reqs = {}
      for sla in self.data['sla']:
        e2e = {}
        # Save delay/bandwidth values
        for param in sla['assurance_parameters']:
          if param['id'] == 'delay':
            e2e['delay'] = int(param['value'])
          if param['id'] == 'bandwidth':
            e2e['bandwidth'] = int(param['value'])
        # If delay and/or bandwidth is exist in an SLA --> save the SLA as an
        # E2E requirement
        if e2e:
          reqs[sla['id']] = e2e
      return reqs
    except KeyError:
      self.log.error("Missing required field for 'sla' in data:\n%s!" % self)

  def get_vlink_sla_ref (self, id):
    """
    Get the referenced SLA id of the virtual link given by id.

    :param id: virtual link id
    :type id: str
    :return:  id of SLA entry aka e2e requirement link
    :rtype: 3str
    """
    for vld in self.data['vld']['virtual_links']:
      if vld['vld_id'] == id:
        return vld['sla_ref_id']

  def get_nfps (self):
    """
    Get the list of NFP from the defined single VNF-FG as 'graph' list.
    The 'graph' list must be ordered from the source to the destination nodes.

    :return: list of NFP which is a list of virtual link ids
    :rtype: list
    """
    try:
      if len(self.data['vnffgd']['vnffgs']) > 1:
        self.log.error("Only 1 VNF-FG instance is supported!")
        return
      nfps = self.data['vnffgd']['vnffgs'][0]['network_forwarding_path']
      return [nfp['graph'] for nfp in nfps]
    except KeyError:
      self.log.error(
        "Missing required field for 'network_forwarding_path' in NFP: %s!"
        % self.id)

  def get_port_from_vlink (self, vlink_id, index):
    """
    Get the container node id and port id of the endpoint given by index from
    a virtual link given by vlink_id.
    The index mark the position of the endpoint in the 'connections' list which
    must contains exactly 2 elements in the ordered: [src, dst].
    If the node id does not stat with 'VNF' the node is considered as an
    VNF-FG endpoint aka a SAP. In that case the port value is None.

    :param vlink_id: virtual link id
    :type vlink_id: str
    :param index: index of link endpoint in 'connections' list
    :type index: int
    :return: tuple of node id and port id
    :rtype: tuple
    """
    try:
      for vld in self.data['vld']['virtual_links']:
        if vld['vld_id'] == vlink_id:
          try:
            src = vld['connections'][index]
          except IndexError:
            return vld['alias'], None
          # Get VNF node/port values
          if src.startswith('VNF#'):
            parts = src.split(':')
            return parts[0].lstrip('VNF#'), parts[1].lstrip('ext_')
    except KeyError:
      self.log.error("Missing required field for 'vlink' in NSD: %s!" % self.id)

  def get_src_port (self, vlink_id):
    """
    Return the source node, port id of a virtual link given by vlink_id.

    :param vlink_id: virtual link id
    :type vlink_id: str
    :return: the source node,port of the given virtual link
    :rtype: tuple
    """
    return self.get_port_from_vlink(vlink_id=vlink_id, index=0)

  def get_dst_port (self, vlink_id):
    """
    Return the destination node, port id of a virtual link given by vlink_id.

    :param vlink_id: virtual link id
    :type vlink_id: str
    :return: the destination node,port of the given virtual link
    :rtype: tuple
    """
    return self.get_port_from_vlink(vlink_id=vlink_id, index=1)


class MissingVNFDException(Exception):
  """
  Exception class signaling missing VNFD from Catalogue.
  """

  def __init__ (self, vnf_id=None):
    self.vnf_id = vnf_id

  def __str__ (self):
    return "Missing VNF id: %s from Catalogue!" % self.vnf_id


class VNFCatalogue(object):
  """
  Container class for VNFDs.
  """
  # VNF_STORE_ENABLED = False
  VNF_STORE_ENABLED = True

  def __init__ (self, remote_store=False, url=None, catalogue_dir=None,
                logger=None):
    """
    Constructor.

    :param logger: optional logger
    """
    self.log = logger if logger is not None else logging.getLogger(
      self.__class__.__name__)
    self.catalogue = {}
    if catalogue_dir:
      self.VNF_CATALOGUE_DIR = catalogue_dir
    if remote_store:
      self.VNF_STORE_ENABLED = True
    self.vnf_store_url = url
    self._full_catalogue_path = None

  def register (self, id, data):
    """
    Add a VNF as a VNFWrapper class with the given name.
    Return if the registering was successful.

    :param id: id of the VNF
    :type id: str
    :param data: VNFD as a :any:`VNFWrapper` class
    :return: result of registering
    :rtype: bool
    """
    if isinstance(data, VNFWrapper):
      self.catalogue[id] = data
      self.log.info("VNFD is registered with id: %s" % id)
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
      return self.__request_vnf_from_remote_store(id)
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
      # Iterate over catalogue dir
      for vnf in os.listdir(catalogue_dir):
        if vnf.startswith('.'):
          continue
        vnfd_file = os.path.join(catalogue_dir, vnf)
        with open(vnfd_file) as f:
          # Parse VNFD from JSOn files as VNFWrapper class
          vnfd = json.load(f, object_hook=self.__vnfd_object_hook)
          vnfd.vnfd_file = vnfd_file
          # Register VNF into catalogue
          self.register(id=os.path.splitext(vnf)[0], data=vnfd)
      return self

  def __request_vnf_from_remote_store (self, vnf_id):
    response = requests.get(url=os.path.join(self.vnf_store_url, str(vnf_id)))
    if not response.ok:
      self.log.error("Got error during VNFD request")
      return None
    vnfd = json.loads(response.text, object_hook=self.__vnfd_object_hook)
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


class TNOVAConverter(object):
  """
  Converter class for NSD --> NFFG conversion.
  """
  # DEFAULT_SAP_PORT_ID = None  # None = generated an UUID by defaults
  DEFAULT_SAP_PORT_ID = 1

  def __init__ (self, logger=None, vnf_catalogue=None):
    """
    Constructor.

    :param logger: optional logger
    """
    self.log = logger if logger is not None else logging.getLogger(
      self.__class__.__name__)
    if vnf_catalogue is not None:
      self.catalogue = vnf_catalogue

  def parse_nsd_from_file (self, nsd_file):
    """
    Parse the given NFD as :any`NSWrapper` from file given by nsd_file.
    nsd_path can be relative to $PWD.

    :param nsd_file: NSD file path
    :type nsd_file: str
    :return: parsed NSD
    :rtype: :any:`NSWrapper`
    """
    try:
      with open(os.path.abspath(nsd_file)) as f:
        return json.load(f, object_hook=self.__nsd_object_hook)
    except IOError as e:
      self.log.error("Got error during NSD parse: %s" % e)
      sys.exit(1)

  @staticmethod
  def __nsd_object_hook (obj):
    """
    Object hook function for converting top dict into :any:`NSWrapper`
    instance.
    """
    return NSWrapper(raw=obj['nsd']) if 'nsd' in obj else obj

  def __convert_nfs (self, nffg, ns, vnfs):
    """
    Create NF nodes in given NFFG based on given NF and VNFs.

    :param nffg: main NFFG object
    :type nffg: :any:`NFFG`
    :param ns: NSD wrapper object
    :type ns: :any:`NSWrapper`
    :param vnfs: VNF catalogue
    :type vnfs: :any:`VNFCatalogue`
    :return: None
    """
    # Add NFs
    for nf_id in ns.get_vnfs():
      vnf = vnfs.get_by_id(nf_id)
      if vnf is None:
        self.log.error(
          "VNFD with id: %s is not found in the VNFCatalogue!" % nf_id)
        raise MissingVNFDException(nf_id)
      node_nf = nffg.add_nf(id=vnf.get_vnf_id(),
                            name=vnf.name,
                            func_type=vnf.get_vnf_type(),
                            dep_type=vnf.get_deployment_type(),
                            **vnf.get_resources())
      # Add ports to NF
      for port in vnf.get_ports():
        try:
          port_id = int(port)
        except ValueError:
          port_id = port
        node_nf.add_port(id=port_id)
        self.log.info("Added NF: %s" % node_nf)

  def __convert_saps (self, nffg, ns, vnfs):
    """
    Create SAP nodes in given NFFG based on given NF and VNFs.

    :param nffg: main NFFG object
    :type nffg: :any:`NFFG`
    :param ns: NSD wrapper object
    :type ns: :any:`NSWrapper`
    :param vnfs: VNF catalogue
    :type vnfs: :any:`VNFCatalogue`
    :return: None
    """
    # Add SAPs
    for cp in ns.get_saps():
      try:
        sap_id = int(cp)
      except ValueError:
        sap_id = cp
      node_sap = nffg.add_sap(id=sap_id,
                              name=sap_id)
      # Add default port to SAP with random name
      node_sap.add_port(id=self.DEFAULT_SAP_PORT_ID)
      self.log.info("Added SAP: %s" % node_sap)

  def __convert_sg_hops (self, nffg, ns, vnfs):
    """
    Create SG hop edges in given NFFG based on given NF and VNFs.

    :param nffg: main NFFG object
    :type nffg: :any:`NFFG`
    :param ns: NSD wrapper object
    :type ns: :any:`NSWrapper`
    :param vnfs: VNF catalogue
    :type vnfs: :any:`VNFCatalogue`
    :return: None
    """
    # Add SG hops
    for vlink in ns.get_vlinks():
      # Parse src params
      src_node = vnfs.get_by_id(vlink['src_node'])
      if src_node is not None:
        src_node_id = src_node.get_vnf_id()
        try:
          src_port_id = int(vlink['src_port'])
        except ValueError:
          src_port_id = vlink['src_port']
        src_port = nffg[src_node_id].ports[src_port_id]
      # If the id is not VNF Catalogue, it must be a SAP
      else:
        src_port = nffg[vlink['src_node']].ports.container[0]
      # Parse dst params
      dst_node = vnfs.get_by_id(vlink['dst_node'])
      if dst_node is not None:
        dst_node_id = dst_node.get_vnf_id()
        try:
          dst_port_id = int(vlink['dst_port'])
        except ValueError:
          dst_port_id = vlink['dst_port']
        dst_port = nffg[dst_node_id].ports[dst_port_id]
      # If the id is not VNF Catalogue, it must be a SAP
      else:
        dst_port = nffg[vlink['dst_node']].ports.container[0]
      # Add SG hop
      link_sg = nffg.add_sglink(id=vlink['id'],
                                src_port=src_port,
                                dst_port=dst_port)
      self.log.info("Added SG hop: %s" % link_sg)

  def __convert_e2e_reqs (self, nffg, ns, vnfs):
    """
    Create E2E Requirement edges in given NFFG based on given NF and VNFs.

    :param nffg: main NFFG object
    :type nffg: :any:`NFFG`
    :param ns: NSD wrapper object
    :type ns: :any:`NSWrapper`
    :param vnfs: VNF catalogue
    :type vnfs: :any:`VNFCatalogue`
    :return: None
    """
    # Add e2e requirement links
    # Get service chains from NFP.graph
    reqs = ns.get_e2e_reqs()
    # Get E2E requirements from SLAs
    for chain in ns.get_nfps():
      self.log.debug("Process chain: %s" % chain)
      # Create set from SLA ids referred in vlinks in NFP graph list
      req_id = {ns.get_vlink_sla_ref(id) for id in chain}
      # Only one SLA (aka requirement) must be referred through a NFP
      if len(req_id) > 1:
        self.log.error(
          "Multiple SLA id: %s has detected in the NFP: %s! Skip SLA "
          "processing..." % (req_id, chain))
      else:
        req_id = req_id.pop()
      self.log.debug("Detected Requirement link ref: %s" % req_id)
      if req_id not in reqs:
        self.log.warning(
          "SLA definition with id: %s was not found in detected SALs: %s!" % (
            req_id, reqs))
        continue
      src_node, src_port = ns.get_src_port(vlink_id=chain[0])
      # If src_port is a valid port of a VNF
      if src_port is not None:
        try:
          src_port = int(src_port)
        except ValueError:
          pass
        src = nffg[src_node].ports[src_port]
      # If src_node is a SAP but the default SAP port constant is set
      elif self.DEFAULT_SAP_PORT_ID is not None:
        src = nffg[src_node].ports[self.DEFAULT_SAP_PORT_ID]
      # Else get the only port from SAP
      else:
        src = nffg[src_node].ports.container[0]
      self.log.debug("Found src port object: %s" % src)
      dst_node, dst_port = ns.get_dst_port(vlink_id=chain[-1])
      # If dst_port is a valid port of a VNF
      if dst_port is not None:
        try:
          dst_port = int(dst_port)
        except ValueError:
          pass
        dst = nffg[dst_node].ports[dst_port]
      # If dst_node is a SAP but the default SAP port constant is set
      elif self.DEFAULT_SAP_PORT_ID is not None:
        dst = nffg[dst_node].ports[self.DEFAULT_SAP_PORT_ID]
      # Else get the only port from SAP
      else:
        dst = nffg[dst_node].ports.container[0]
        self.log.debug("Found dst port object: %s" % dst)
      req_link = nffg.add_req(id=req_id,
                              src_port=src,
                              dst_port=dst,
                              delay=reqs[req_id]['delay'],
                              bandwidth=reqs[req_id]['bandwidth'],
                              sg_path=[int(id) for id in chain])
      self.log.info("Added requirement link: %s" % req_link)

  def convert (self, nsd_file):
    """
    Main converter function which parse the VNFD and NSD filed, create the
    VNF catalogue and convert the NSD given by nsd_file into :any:`NFFG`.

    :param nsd_file: NSD field path
    :type nsd_file: str
    :return: created NFFG object
    :rtype: :any:`NFFG`
    """
    # Parse required descriptors
    self.log.info("Parse Network Service (NS) from NSD file: %s" % nsd_file)
    ns = self.parse_nsd_from_file(nsd_file)
    self.log.info(
      "Parse VNFs from VNFD files under: %s" % self.catalogue.VNF_CATALOGUE_DIR)
    vnfs = self.catalogue.parse_vnf_catalogue_from_folder()
    self.log.debug("Registered VNFs: %s" % vnfs.catalogue.keys())
    # Create main NFFG object
    nffg = NFFG(id=ns.id, name=ns.name)
    # Convert NFFG elements
    try:
      self.log.debug("Convert NF nodes...")
      self.__convert_nfs(nffg=nffg, ns=ns, vnfs=vnfs)
      self.log.debug("Convert SAP nodes...")
      self.__convert_saps(nffg=nffg, ns=ns, vnfs=vnfs)
      self.log.debug("Convert Service Graph hop edges...")
      self.__convert_sg_hops(nffg=nffg, ns=ns, vnfs=vnfs)
      self.log.debug("Convert E2E Requirement edges...")
      self.__convert_e2e_reqs(nffg=nffg, ns=ns, vnfs=vnfs)
    except MissingVNFDException as e:
      self.log.exception(e)
    except:
      self.log.exception(
        "Got unexpected exception during NSD -> NFFG conversion!")
    # Return with assembled NFFG
    return nffg


if __name__ == "__main__":
  parser = argparse.ArgumentParser(
    description="TNOVAConverter: Converting Network Services "
                "from T-NOVA: NSD and VNFD files "
                "into UNIFY: NFFG", add_help=True)
  parser.add_argument("-c", "--catalogue", metavar="cdir",
                      default="vnf_catalogue",
                      help="path to the catalogue dir contains the VNFD files "
                           "(default: ./vnf_catalogue)")
  parser.add_argument("-d", "--debug", action="store_const", dest="loglevel",
                      const=logging.DEBUG, default=logging.INFO,
                      help="run in debug mode")
  parser.add_argument("-n", "--nsd", metavar="npath", default="nsd.json",
                      help="path of NSD file contains the Service Request "
                           "(default: ./nsd.json)")

  args = parser.parse_args()
  log = logging.getLogger()
  logging.basicConfig(level=args.loglevel)
  catalogue = VNFCatalogue(remote_store=False, logger=log,
                           catalogue_dir=args.catalogue)
  catalogue.VNF_STORE_ENABLED = False
  converter = TNOVAConverter(logger=log, vnf_catalogue=catalogue)
  log.info("Start converting NS: %s..." % args.nsd)
  nffg = converter.convert(nsd_file=args.nsd)
  log.info("Generated NFFG:\n%s" % nffg.dump())
