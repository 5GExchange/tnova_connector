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
import re
import sys

from colored_logger import ColoredLogger
from nffg_lib.nffg import NFFG
from nsd_wrapper import NSWrapper
from vnf_catalogue import VNFCatalogue, MissingVNFDException


class TNOVAConverter(object):
  """
  Converter class for NSD --> NFFG conversion.
  """
  LOGGER_NAME = "TNOVAConverter"
  # DEFAULT_SAP_PORT_ID = None  # None = generated an UUID by defaults
  DEFAULT_SAP_PORT_ID = 1

  def __init__ (self, logger=None, vnf_catalogue=None):
    """
    Constructor.

    :param logger: optional logger
    """
    if logger is not None:
      self.log = logger.getChild(self.LOGGER_NAME)
      # self.log.name = self.LOGGER_NAME
    else:
      logging.getLogger(self.__class__.__name__)
    if vnf_catalogue is not None:
      self.__catalogue = vnf_catalogue
    else:
      self.__catalogue = VNFCatalogue(logger=logger)
    self.vlan_register = {}

  def __str__ (self):
    return "%s()" % self.__class__.__name__

  def initialize (self):
    """
    Initialize TNOVAConverter by reading cached VNFDs from file.
    
    :return: None
    """
    self.log.info("Initialize %s..." % self.__class__.__name__)
    self.log.debug("Use VNFCatalogue: %s" % self.__catalogue)

  def parse_nsd_from_file (self, nsd_file):
    """
    Parse the given NFD as :any`NSWrapper` from file given by nsd_file.
    nsd_path can be relative to $PWD.

    :param nsd_file: NSD file path
    :type nsd_file: str
    :return: parsed NSD
    :rtype: NSWrapper
    """
    try:
      with open(os.path.abspath(nsd_file)) as f:
        return json.load(f, object_hook=self.__nsd_object_hook)
    except IOError as e:
      self.log.error("Got error during NSD parse: %s" % e)
      sys.exit(1)

  @classmethod
  def parse_nsd_from_text (cls, raw):
    """
    Parse the given NFD as :any`NSWrapper` from raw data.

    :param raw: raw NSD data
    :type raw: str
    :return: parsed NSD
    :rtype: NSWrapper
    """
    return json.load(raw, object_hook=cls.__nsd_object_hook)

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
    :type nffg: NFFG
    :param ns: NSD wrapper object
    :type ns: NSWrapper
    :param vnfs: VNF catalogue
    :type vnfs: VNFCatalogue
    :return: None
    """
    # Add NFs
    for domain, nf_id in ns.get_vnfs():
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
      self.log.debug("Create VNF: %s" % node_nf)
      # Add ports to NF
      for port in vnf.get_ports():
        nf_port = node_nf.add_port(id=port)
        self.log.debug("Added NF port: %s" % nf_port)
      # Detect INTERNET ports
      for iport in vnf.get_internet_ports():
        if iport not in node_nf.ports:
          # INTERNET port is not external
          nf_port = node_nf.add_port(id=iport, sap="INTERNET")
          self.log.debug("Added new INTERNET port: %s" % nf_port)
        else:
          nf_port = node_nf.ports[iport]
          # Set SAP attribute for INTERNET port
          nf_port.sap = "INTERNET"
      # Add metadata
      for md, value in vnf.get_metadata().iteritems():
        if md == 'bootstrap_script':
          node_nf.add_metadata(name='command', value=value)
          self.log.debug("Found command: %s", value)
        elif md == 'vm_image':
          node_nf.add_metadata(name='image', value=value)
          self.log.debug("Found image: %s", value)
        elif md == 'variables':
          node_nf.add_metadata(name='environment',
                               value=self._parse_variables(value=value))
          self.log.debug("Found environment: %s",
                         node_nf.metadata['environment'])
        # Add port bindings
        elif md == 'networking_resources':
          for iport in vnf.get_internet_ports():
            port = node_nf.ports[iport]
            port.l4 = self._parse_binding(value=value)
            self.log.debug("Detected port bindings: %s" % port.l4)
      self.log.info("Added NF: %s" % node_nf)

  @staticmethod
  def _parse_variables (value):
    envs = {}
    envs.update(map(lambda x: x.split('=', 1) if '=' in x else (x, None),
                    [str(kv) for kv in value.split()]))
    return str(envs).replace('"', "'")

  @staticmethod
  def _parse_binding (value):
    ports = {}
    ports.update(map(lambda x: ("%s/tcp" % x, ('', x)),
                     [int(p) for p in value.replace(',', ' ').split()]))
    return str(ports).replace('"', "'")

  def __convert_saps (self, nffg, ns, vnfs):
    """
    Create SAP nodes in given NFFG based on given NF and VNFs.

    :param nffg: main NFFG object
    :type nffg: NFFG
    :param ns: NSD wrapper object
    :type ns: NSWrapper
    :param vnfs: VNF catalogue
    :type vnfs: VNFCatalogue
    :return: None
    """
    # Add SAPs
    for cp in ns.get_saps():
      cp = cp.split(':')[0]
      try:
        sap_id = int(cp)
      except ValueError:
        sap_id = cp
      if sap_id in nffg:
        self.log.info("SAP: %s was already added, skip" % sap_id)
        continue
      node_sap = nffg.add_sap(id=sap_id,
                              name=sap_id)
      self.log.info("Added SAP: %s" % node_sap)
      # Add default port to SAP with random name
      sap_port = node_sap.add_port(id=self.DEFAULT_SAP_PORT_ID)
      self.log.info("Added SAP port: %s" % sap_port)

  def __process_tag (self, abstract_id):
    """
    Generate a valid VLAN id from the raw_id data which derived from directly
    an SG hop link id.

    Moved from: escape.adapt.managers.InternalDomainManager#__process_tag

    :param abstract_id: raw link id
    :type abstract_id: str or int
    :return: valid VLAN id
    :rtype: int
    """
    # Check if the abstract tag has already processed
    if abstract_id in self.vlan_register:
      self.log.debug("Found already register TAG ID: %s ==> %s" % (
        abstract_id, self.vlan_register[abstract_id]))
      return self.vlan_register[abstract_id]
    # Check if the raw_id is a valid number
    try:
      vlan_id = int(abstract_id)
      # Check if the raw_id is free
      if 0 < vlan_id < 4095 and vlan_id not in self.vlan_register.itervalues():
        self.vlan_register[abstract_id] = vlan_id
        self.log.debug(
          "Abstract ID a valid not-taken VLAN ID! Register %s ==> %s" % (
            abstract_id, vlan_id))
        return vlan_id
    except ValueError:
      # Cant be converted to int, continue with raw_id processing
      pass
    trailer_num = re.search(r'\d+$', abstract_id)
    # If the raw_id ends with number
    if trailer_num is not None:
      # Check if the trailing number is a valid VLAN id (0 and 4095 are
      # reserved)
      trailer_num = int(trailer_num.group())  # Get matched data from Match obj
      # Check if the VLAN candidate is free
      if 0 < trailer_num < 4095 and \
            trailer_num not in self.vlan_register.itervalues():
        self.vlan_register[abstract_id] = trailer_num
        self.log.debug(
          "Trailing number is a valid non-taken VLAN ID! Register %s ==> "
          "%s..." % (abstract_id, trailer_num))
        return trailer_num
        # else Try to find a free VLAN
      else:
        self.log.debug(
          "Detected trailing number: %s is not a valid VLAN or already "
          "taken!" % trailer_num)
    # No valid VLAN number has found from abstract_id, try to find a free VLAN
    for vlan in xrange(1, 4094):
      if vlan not in self.vlan_register.itervalues():
        self.vlan_register[abstract_id] = vlan
        self.log.debug(
          "Generated and registered VLAN id %s ==> %s" % (abstract_id, vlan))
        return vlan
    # For loop is exhausted
    else:
      self.log.error("No available VLAN id found!")
      return None

  def __convert_sg_hops (self, nffg, ns, vnfs):
    """
    Create SG hop edges in given NFFG based on given NF and VNFs.

    :param nffg: main NFFG object
    :type nffg: NFFG
    :param ns: NSD wrapper object
    :type ns: NSWrapper
    :param vnfs: VNF catalogue
    :type vnfs: VNFCatalogue
    :return: None
    """
    # Add SG hops
    for vlink in ns.get_vlinks():
      # Parse src params
      src_node = vnfs.get_by_id(vlink['src_node'])
      if src_node is not None:
        src_node_id = src_node.get_vnf_id()
        src_port_id = vlink['src_port']
        src_port = nffg[src_node_id].ports[src_port_id]
      # If the id is not VNF Catalogue, it must be a SAP
      else:
        src_port = nffg[vlink['src_node']].ports.container[0]
      self.log.debug("Got src port: %s" % src_port)
      # Parse dst params
      dst_node = vnfs.get_by_id(vlink['dst_node'])
      if dst_node is not None:
        dst_node_id = dst_node.get_vnf_id()
        dst_port_id = vlink['dst_port']
        dst_port = nffg[dst_node_id].ports[dst_port_id]
      # If the id is not VNF Catalogue, it must be a SAP
      else:
        dst_port = nffg[vlink['dst_node']].ports.container[0]
      self.log.debug("Got dst port: %s" % dst_port)
      # Generate SG link id compatible with ESCAPE's naming convention
      link_id = self.__process_tag(vlink['id'])
      # Add SG hop
      link_sg = nffg.add_sglink(id=link_id,
                                src_port=src_port,
                                dst_port=dst_port,
                                flowclass=vlink['flowclass'],
                                delay=vlink['delay'],
                                bandwidth=vlink['bandwidth'])
      self.log.info("Added SG hop: %s" % link_sg)

  def __convert_e2e_reqs (self, nffg, ns, vnfs):
    """
    Create E2E Requirement edges in given NFFG based on given NF and VNFs.

    :param nffg: main NFFG object
    :type nffg: NFFG
    :param ns: NSD wrapper object
    :type ns: NSWrapper
    :param vnfs: VNF catalogue
    :type vnfs: VNFCatalogue
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
      print req_id
      if len(req_id) < 1:
        self.log.warning("No SLA id has detected in the NFP: %s! "
                         "Skip SLA processing..." % chain)
        return
      elif len(req_id) > 1:
        self.log.error("Multiple SLA id: %s has detected in the NFP: %s! "
                       "Skip SLA processing..." % (req_id, chain))
        return
      else:
        req_id = req_id.pop()
      self.log.debug("Detected Requirement link ref: %s" % req_id)
      if req_id not in reqs:
        self.log.warning(
          "SLA definition with id: %s was not found in detected SLAs: %s!" % (
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
    self.log.info("Parsing Network Service (NS) from NSD file: %s" % nsd_file)
    ns = self.parse_nsd_from_file(nsd_file)
    if not self.__catalogue.VNF_STORE_ENABLED:
      self.log.info("Parsing new VNFs from VNFD files under: %s" %
                    self.__catalogue.VNF_CATALOGUE_DIR)
      vnfs = self.__catalogue.parse_vnf_catalogue_from_folder()
      self.log.debug("Registered VNFs: %s" % vnfs.get_registered_vnfs())
    # Create main NFFG object
    nffg = NFFG(id=ns.id, service_id=ns.id, name=ns.name)
    # Convert NFFG elements
    try:
      self.log.debug("Convert NF nodes...")
      self.__convert_nfs(nffg=nffg, ns=ns, vnfs=self.__catalogue)
      self.log.debug("Convert SAP nodes...")
      self.__convert_saps(nffg=nffg, ns=ns, vnfs=self.__catalogue)
      self.log.debug("Convert Service Graph hop edges...")
      self.__convert_sg_hops(nffg=nffg, ns=ns, vnfs=self.__catalogue)
      self.log.debug("Convert E2E Requirement edges...")
      self.__convert_e2e_reqs(nffg=nffg, ns=ns, vnfs=self.__catalogue)
    except MissingVNFDException as e:
      self.log.error(e)
      return None
    except:
      self.log.exception(
        "Got unexpected exception during NSD -> NFFG conversion!")
      return None
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
  parser.add_argument("-n", "--nsd", metavar="npath",
                      default="nsds/nsd_from_folder.json",
                      help="path of NSD file contains the Service Request "
                           "(default: ./nsds/nsd_from_folder.json)")
  parser.add_argument("-o", "--offline", action="store_true", default=False,
                      help="work offline and read the VNFDs from files"
                           "(default: False)")
  args = parser.parse_args()
  # logging.setLoggerClass(ColoredLogger)
  # logging.basicConfig(level=args.loglevel)
  # log = logging.getLogger(__name__)
  # log.setLevel(args.loglevel)
  log = ColoredLogger.configure(level=args.loglevel)
  catalogue = VNFCatalogue(use_remote=False, logger=log,
                           cache_dir=args.catalogue,
                           vnf_store_url="http://172.16.178.128:8080/NFS/vnfds")
  # catalogue.VNF_STORE_ENABLED = True
  catalogue.VNF_STORE_ENABLED = not args.offline
  converter = TNOVAConverter(logger=log, vnf_catalogue=catalogue)
  log.info("Start converting NS: %s..." % args.nsd)
  nffg = converter.convert(nsd_file=args.nsd)
  if nffg is not None:
    log.info("Generated NFFG:\n%s" % nffg.dump())
