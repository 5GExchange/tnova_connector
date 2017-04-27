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

from vnf_catalogue import AbstractDescriptorWrapper


class NSWrapper(AbstractDescriptorWrapper):
  """
  Wrapper class for VNFD data structure.
  """
  # Constants
  LINK_TYPE = ("E-LINE", "INTERNET")
  NS_EXTERNAL_PORT_PREFIX = 'ns_ext_'
  VNFDS_SEPARATOR = ':'
  VNFD_DOMAIN_PREFIX = 'domain#'
  VNFD_VNF_PREFIX = 'vnf#'
  VNFD_NS_PREFIX = 'ns#'
  VNFD_EXTERNAL_PORT_PREFIX = 'ext_'

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
      return [self.__vnfd_connection_point_parser(raw=vnf)[0:2]
              for vnf in self.data['vnfds']]
    except KeyError as e:
      self.log.error("Missing required field: %s for 'vnfds' in NSD: %s!"
                     % (e.message, self.id))
    except ValueError as e:
      self.log.error("Listed VNF id in 'vnfds': %s is not a valid integer!" % e)

  def __vnfd_connection_point_parser (self, raw):
    """
    Parse, split and convert VNFD parts from NSD's list, "vnfds".
    Missing element substituted with None.
    
    :param raw: raw ID in "vnfds" list
    :type raw: str
    :return: tuple of parsed domain, VNFD id and port
    :rtype: (str, int, int)
    """
    domain, id, port = None, None, None
    for tag in raw.split(self.VNFDS_SEPARATOR):
      lower_tag = tag.lower()
      if lower_tag.startswith(self.VNFD_DOMAIN_PREFIX):
        domain = tag[len(self.VNFD_DOMAIN_PREFIX):]
      elif lower_tag.startswith(self.VNFD_VNF_PREFIX):
        id = tag[len(self.VNFD_VNF_PREFIX):]
      elif lower_tag.startswith(self.VNFD_NS_PREFIX):
        id = tag[len(self.VNFD_NS_PREFIX):]
      elif lower_tag.startswith(self.VNFD_EXTERNAL_PORT_PREFIX):
        port = tag[len(self.VNFD_EXTERNAL_PORT_PREFIX):]
      # Check old format(no prefixes) for backward compatibility
      elif lower_tag.isdigit():
        id = tag
      else:
        self.log.warning("Unrecognized prefix in: %s" % tag)
    self.log.debug("Found VNFD params - domain: %s, VNF: %s, port: %s"
                   % (domain, id, port))
    try:
      id = int(id)
    except ValueError:
      self.log.warning("Detected ID: %s is not valid integer!" % id)
    try:
      port = int(port)
    except TypeError:
      # If port has remained None
      pass
    except ValueError:
      self.log.warining("Detected port: %s is not valid integer!" % port)
    return domain, id, port

  def get_saps (self):
    """
    Get the list of SAPs which come from the 'connection_points' list.

    :return: SAP ids
    :rtype: list
    """
    try:
      # return self.data['connection_points']
      # return self.data['connection_points']
      saps = []
      for cp in self.data['vnffgd']['vnffgs'][0]['network_forwarding_path'][0][
        'connection_points']:
        if cp.startswith(self.NS_EXTERNAL_PORT_PREFIX):
          ext_point = cp.lstrip(self.NS_EXTERNAL_PORT_PREFIX)
          if ext_point not in saps:
            saps.append(ext_point)
            self.log.debug("Found SAP: %s" % ext_point)
      return saps
    except KeyError as e:
      self.log.error("Missing required field: %s for SAPs in "
                     "'connection_points' in NSD: %s!" % (e.message, self.id))

  def __parse_vlink_connection (self, conn):
    """
    Return parsed node and port ID of given connection point: ``conn``.
     
    :param conn: connection point in raw string
    :type conn: str
    :return: tuple of node and port IDs
    :rtype: (int, int)
    """
    domain, vnf_id, port = self.__vnfd_connection_point_parser(raw=conn)
    if not all((vnf_id, port)):
      self.log.error("Missing VNF prefix: %s from connection: %s" % conn)
    return vnf_id, port

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
      srcSAP_list = []
      for vlink in self.data['vld']['virtual_links']:
        if vlink['connectivity_type'] not in self.LINK_TYPE:
          self.log.warning("Only Link types: %s are supported! Skip Virtual"
                           " link processing:\n%s" % (self.LINK_TYPE, vlink))
          continue
        hop = {'flowclass': None,
               'delay': None,
               'bandwidth': None}
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
          direction = None
          node, port = self.__parse_vlink_connection(vlink['connections'][0])
          sap_node, sap_port = vlink['alias'].split(':')[0], None
          # If explicit direction (in/out) is given: 
          if len(vlink['alias'].split(':')) > 1:
            if vlink['alias'].split(':')[1] == 'in':
              direction = 'in'
            elif vlink['alias'].split(':')[1] == 'out':
              direction = 'out'
          else:
            # No explicit direction defined
            # Try to detect SAP role
            if sap_node not in srcSAP_list:
              # First virtual link referring the SAP is considered as the
              # ingress (multiple ingress links will be supported if
              # marketplace supports flowclass/metadata on links)
              direction = 'in'
            else:
              # We have already processed the rule for ingress traffic
              direction = 'out'
          if direction == 'in':
            # Source SAP
            hop['src_node'], hop['src_port'] = sap_node, sap_port
            hop['dst_node'], hop['dst_port'] = node, port
            srcSAP_list.append(sap_node)
            self.log.debug("Detected starting SAP")
          else:
            # Destination SAP
            hop['src_node'], hop['src_port'] = node, port
            hop['dst_node'], hop['dst_port'] = sap_node, sap_port
            self.log.debug("Detected ending SAP")
        self.log.debug("src: %s - %s" % (hop['src_node'], hop['src_port']))
        self.log.debug("dst: %s - %s" % (hop['dst_node'], hop['dst_port']))
        # Ugly hack for processing delay requirement and flowclass on link
        if vlink['qos']['delay']:
          hop['delay'] = vlink['qos']['delay']
          self.log.debug("delay requirement: %s" % hop['delay'])
        if vlink['qos']['flowclass']:
          hop['flowclass'] = vlink['qos']['flowclass']
          self.log.debug("flowclass: %s" % hop['flowclass'])
        self.log.debug("Detected link data - delay: %s, flowclass: %s"
                       % (hop['delay'], hop['flowclass']))
        hops.append(hop)
      return hops
    except KeyError as e:
      self.log.error("Missing required field: %s for 'vld' in data:\n%s!"
                     % (e.message, self))

  def get_e2e_reqs (self):
    """
    Get list of E2E requirement link params: id, delay, bandwidth which come
    from 'sla' fields.

    :return: list of requirement link params
    :rtype: list of dict
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
    except KeyError as e:
      self.log.error("Missing required field: %s for 'sla' in data:\n%s!"
                     % (e.message, self))

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
    except KeyError as e:
      self.log.error(
        "Missing required field: %s for 'network_forwarding_path' in NFP: %s!"
        % (e.message, self.id))

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
            return vld['alias'].split(':')[0], None
          # Get VNF node/port values
          return self.__vnfd_connection_point_parser(src)[0:2]
    except KeyError as e:
      self.log.error("Missing required field: %s for 'vlink' in NSD: %s!"
                     % (e.message, self.id))

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
