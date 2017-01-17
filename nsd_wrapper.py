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
      srcSAP_list = []
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
          if sap_node not in srcSAP_list:
            # Source SAP
            # First virtual link referring the SAP is considered as the
            # ingress (multiple ingress links will be supported if
            # marketplace supports flowclass/metadata on links)
            hop['src_node'], hop['src_port'] = sap_node, sap_port
            hop['dst_node'], hop['dst_port'] = node, port
            srcSAP_list.append(sap_node)
            self.log.debug("Detected starting SAP")
          else:
            # Destination SAP
            # We have already processed the rule for ingress traffic
            hop['src_node'], hop['src_port'] = node, port
            hop['dst_node'], hop['dst_port'] = sap_node, sap_port
            self.log.debug("Detected ending SAP")
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
