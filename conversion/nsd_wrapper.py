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
import itertools
import logging

from vnf_catalogue import AbstractDescriptorWrapper


class NSWrapper(AbstractDescriptorWrapper):
  """
  Wrapper class for VNFD data structure.
  """
  # Constants
  SG_LINK_TYPE = "E-LINE"
  NS_EXTERNAL_PORT_PREFIX = 'ns_ext_'
  VNFDS_SEPARATOR = ':'
  VNFD_DOMAIN_PREFIX = 'domain#'
  VNFD_VNF_PREFIX = 'vnf#'
  VNFD_VNF_NUM_SEPARATOR = '-'
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
      return [self.__connection_point_parser(raw=vnf)[0:3]
              for vnf in self.data['vnfds']]
    except KeyError as e:
      self.log.error("Missing required field: %s for 'vnfds' in NSD: %s!"
                     % (e.message, self.id))
    except ValueError as e:
      self.log.error("Listed VNF id in 'vnfds': %s is not a valid integer!" % e)

  def get_vnf_instances (self):
    """
    Get the used VNF Instance ids converted to int from the 'vld' list.

    :return: VNF instance ids
    :rtype: list
    """
    try:
      return [self.vnf_ref_id_parser(raw=ref) for ref in
              self.get_constituent_vnfs()]
    except KeyError as e:
      self.log.error("Missing required field: %s for 'vnfds' in NSD: %s!"
                     % (e.message, self.id))
    except ValueError as e:
      self.log.error("Listed VNF id in 'vnfds': %s is not a valid integer!" % e)

  def __connection_point_parser (self, raw):
    """
    Parse, split and convert VNFD parts from NSD's list, "vnfds".
    Missing element substituted with None.
    
    :param raw: raw ID in "vnfds" list
    :type raw: str
    :return: tuple of parsed domain, VNFD id and port
    :rtype: (str, int, int, int)
    """
    domain, id, num, port = None, None, None, None
    self.log.debug("Parsing connection point: %s" % raw)
    for tag in raw.split(self.VNFDS_SEPARATOR):
      lower_tag = tag.lower()
      if lower_tag.startswith(self.VNFD_DOMAIN_PREFIX):
        domain = tag[len(self.VNFD_DOMAIN_PREFIX):]
      elif lower_tag.startswith(self.VNFD_VNF_PREFIX):
        vnf_num = tag[len(self.VNFD_VNF_PREFIX):].split(
          self.VNFD_VNF_NUM_SEPARATOR, 1)
        if len(vnf_num) == 2:
          id, num = vnf_num
        else:
          id = vnf_num.pop()
      elif lower_tag.startswith(self.VNFD_NS_PREFIX):
        id = tag[len(self.VNFD_NS_PREFIX):]
      elif lower_tag.startswith(self.VNFD_EXTERNAL_PORT_PREFIX):
        port = tag[len(self.VNFD_EXTERNAL_PORT_PREFIX):]
      # Check old format(no prefixes) for backward compatibility
      elif lower_tag.isdigit():
        id = tag
      else:
        self.log.warning("Unrecognized prefix in: %s" % tag)
    self.log.debug("Found VNFD params - domain: %s, VNF: %s, num: %s, port: %s"
                   % (domain, id, num, port))
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
    try:
      num = int(num)
    except TypeError:
      # If num has remained None
      pass
    except ValueError:
      self.log.warining("Detected num: %s is not valid integer!" % num)
    return domain, id, num, port

  def vnf_ref_id_parser (self, raw):
    """
    
    :param raw: 
    :return: 
    """
    if '-' in raw:
      vnf, num = raw.rsplit('-', 1)
    else:
      vnf, num = raw, None
    if '@' in vnf:
      vnf_id, domain = vnf.split('@', 1)
    else:
      vnf_id, domain = vnf, None
    try:
      vnf_id = int(vnf_id)
    except ValueError:
      self.log.warning("Detected ID: %s is not valid integer!" % vnf_id)
    try:
      num = int(num)
    except TypeError:
      # If num has remained None
      pass
    except ValueError:
      self.log.warining("Detected num: %s is not valid integer!" % num)
    return domain, vnf_id, num

  def get_saps (self):
    """
    Get the list of SAPs which come from the 'connection_points' list.

    :return: SAP ids
    :rtype: list
    """
    try:
      if len(self.data['vnffgd']['vnffgs']) < 1:
        self.log.error("No VNF-FG instance is detected!")
        return
      if len(self.data['vnffgd']['vnffgs']) > 1:
        self.log.error("Only 1 VNF-FG instance is supported (detected: %s)!"
                       % len(self.data['vnffgd']['vnffgs']))
        self.log.warning("Using the first found VNF-FG: %s"
                         % self.data['vnffgd']['vnffgs'][0]['vnffg_id'])
      saps = []
      for cp in self.data['vnffgd']['vnffgs'][0]['network_forwarding_path'][0][
        'connection_points']:
        if cp.startswith(self.NS_EXTERNAL_PORT_PREFIX):
          ext_point = cp[len(self.NS_EXTERNAL_PORT_PREFIX):]
          if ext_point not in saps:
            saps.append(ext_point)
            self.log.debug("Found new SAP: %s" % ext_point)
      return saps
    except KeyError as e:
      self.log.error("Missing required field: %s for SAPs in "
                     "'connection_points' in NSD: %s!" % (e.message, self.id))

  def parse_vlink_connection (self, conn):
    """
    Return parsed node and port ID of given connection point: ``conn``.
     
    :param conn: connection point in raw string
    :type conn: str
    :return: tuple of node and port IDs
    :rtype: (int, int, int)
    """
    domain, vnf_id, num, port = self.__connection_point_parser(raw=conn)
    if not all((vnf_id, port)):
      self.log.error("Missing VNF prefix: %s from connection: %s" % conn)
    return vnf_id, num, port

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
        if vlink['connectivity_type'] != self.SG_LINK_TYPE:
          self.log.debug("Virtual link: %s is not %s. Skip..."
                         % (vlink['vld_id'], self.SG_LINK_TYPE))
          continue
        hop = {'flowclass': None,
               'delay': None,
               'bandwidth': None}
        try:
          hop['id'] = int(vlink['vld_id'])
        except ValueError:
          hop['id'] = str(vlink['vld_id'])
        # Inter-VNF link
        if vlink['external_access'] is False:
          self.log.debug("Detected Inter-VNF link: %s" % hop['id'])
          if not len(vlink['connections']) == 2:
            self.log.error("Regular NF-NF link: %s must have 2 endpoint! "
                           "Detected: %s" % (vlink['vld_id'],
                                             len(vlink['connections'])))
            continue
          self.log.debug("Detected inter-VNF link: %s" % hop['id'])
          # Check src node/port
          hop['src_node'], hop['src_node_num'], hop['src_port'] = \
            self.parse_vlink_connection(vlink['connections'][0])
          # Check dst node/port
          hop['dst_node'], hop['dst_node_num'], hop['dst_port'] = \
            self.parse_vlink_connection(vlink['connections'][1])
        # External link, one of the endpoint is a SAP
        else:
          self.log.debug("Detected external link: %s" % hop['id'])
          direction = None
          node, num, port = self.parse_vlink_connection(
            vlink['connections'][0])
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
            hop['src_node_num'], hop['dst_node_num'] = None, num
            srcSAP_list.append(sap_node)
            self.log.debug("Detected starting SAP")
          else:
            # Destination SAP
            hop['src_node'], hop['src_port'] = node, port
            hop['dst_node'], hop['dst_port'] = sap_node, sap_port
            hop['src_node_num'], hop['dst_node_num'] = num, None
            self.log.debug("Detected ending SAP")
        self.log.debug("Detected link:  SRC %s : %s  --->  DST %s : %s"
                       % (hop['src_node'], hop['src_port'], hop['dst_node'],
                          hop['dst_port']))
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
      if len(self.data['vnffgd']['vnffgs']) < 1:
        self.log.error("No VNF-FG instance is detected!")
        return
      if len(self.data['vnffgd']['vnffgs']) > 1:
        self.log.error("Only 1 VNF-FG instance is supported (detected: %s)!"
                       % len(self.data['vnffgd']['vnffgs']))
        self.log.warning("Using the first found VNF-FG: %s"
                         % self.data['vnffgd']['vnffgs'][0]['vnffg_id'])
      nfps = self.data['vnffgd']['vnffgs'][0]['network_forwarding_path']
      return [nfp['graph'] for nfp in nfps]
    except KeyError as e:
      self.log.error(
        "Missing required field: %s for 'network_forwarding_path' in NFP: %s!"
        % (e.message, self.id))

  def get_constituent_vnfs (self):
    try:
      if len(self.data['vnffgd']['vnffgs']) < 1:
        self.log.error("No VNF-FG instance is detected!")
        return []
      if len(self.data['vnffgd']['vnffgs']) > 1:
        self.log.error("Only 1 VNF-FG instance is supported (detected: %s)!"
                       % len(self.data['vnffgd']['vnffgs']))
        self.log.warning("Using the first found VNF-FG: %s"
                         % self.data['vnffgd']['vnffgs'][0]['vnffg_id'])
      nfps = self.data['vnffgd']['vnffgs'][0]['network_forwarding_path']
      refs = {cvnf['vnf_ref_id'] for cvnf in itertools.chain.from_iterable(
        nfp['constituent_vnfs'] for nfp in nfps)}
      return list(refs) if refs else []
    except KeyError as e:
      self.log.error(
        "Missing required field: %s for 'network_forwarding_path' in NFP: %s!"
        % (e.message, self.id))
      return []

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
    :return: tuple of node id, num and port id
    :rtype: (int, int, int)
    """
    try:
      for vld in self.data['vld']['virtual_links']:
        if vld['vld_id'] == vlink_id:
          try:
            src = vld['connections'][index]
          except IndexError:
            return vld['alias'].split(':')[0], None
          # Get VNF node/port values
          return self.__connection_point_parser(src)[0:3]
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
