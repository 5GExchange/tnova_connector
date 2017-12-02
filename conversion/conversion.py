#!/usr/bin/env python
# Copyright 2017 Janos Czentye, Raphael Vicente Rosa
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
"""
Contains helper classes for conversion between different NF-FG representations.

Coped from project: ESCAPE
"""
import json
import logging
import re

import virtualizer.virtualizer as virt_lib
from nffg_lib import NFFG, NFFGToolBox, __version__ as N_VERSION
from nffg_lib.nffg_elements import NodeSAP, Constraints
from virtualizer.virtualizer import __version__ as V_VERSION, Virtualizer

# Define VERBOSE logging level
VERBOSE = 5
log = logging.getLogger(__name__)


# noinspection PyShadowingNames
class NFFGConverter(object):
  """
  Convert different representation of NFFG in both ways.
  """
  # port types in Virtualizer
  TYPE_VIRTUALIZER_PORT_ABSTRACT = "port-abstract"
  TYPE_VIRTUALIZER_PORT_SAP = "port-sap"
  # General option names in mapped NFFG assembled by the Mapping algorithm
  OP_TAG = 'TAG'
  OP_UNTAG = 'UNTAG'
  OP_INPORT = 'in_port'
  OP_OUTPUT = 'output'
  OP_FLOWCLASS = "flowclass"
  GENERAL_OPERATIONS = (OP_INPORT, OP_OUTPUT, OP_TAG, OP_UNTAG, OP_FLOWCLASS)
  # Specific tags
  TAG_SG_HOP = "sg_hop"
  # SAP id storing prefix
  SAP_NAME_PREFIX = 'SAP'
  # Operation formats in Virtualizer
  MATCH_TAG = r"dl_tag"
  ACTION_PUSH_TAG = r"push_tag"
  ACTION_POP_TAG = r"pop_tag"
  # Operand delimiters
  LABEL_DELIMITER = '|'
  OP_DELIMITER = ';'
  KV_DELIMITER = '='
  # Other delimiters
  UNIQUE_ID_DELIMITER = '@'
  # Field types
  TYPE_MATCH = "MATCH"
  TYPE_ACTION = "ACTION"
  # Hard-coded constants
  REQUIREMENT_PREFIX = "REQ"

  def __init__ (self, domain=None, logger=None, unique_bb_id=False,
                unique_nf_id=False):
    """
    Init.

    :param domain: domain name
    :type domain: str
    :param logger: optional logger
    :type logger: str or :any:`logging.Logger`
    :param unique_bb_id: generate unique id for nodes
    :type unique_bb_id: bool
    :return: None
    """
    # Save domain name for define domain attribute in infras
    self.domain = domain
    # If clarify_id is True, add domain name as a prefix to the node ids
    self.__unique_bb_id = unique_bb_id
    self.__unique_nf_id = unique_nf_id
    self.log = logger if logger is not None else logging.getLogger(__name__)
    self.log.debug('Created NFFGConverter with domain name: %s' % self.domain)

  def disable_unique_bb_id (self):
    self.log.debug("Disable unique BiSBiS id recreation!")
    self.__unique_bb_id = False

  @classmethod
  def field_splitter (cls, type, field):
    """
    Split the match/action field into a dict-based format for flowrule creation.

    :param type: the name of the field ('MATCH' or 'ACTION')
    :type type: str
    :param field: field data
    :type field: str
    :return: splitted data structure
    :rtype: dict
    """
    ret = {}
    parts = field.split(cls.OP_DELIMITER)
    if len(parts) < 1:
      raise RuntimeError(
        "Wrong format: %s! Separator (%s) not found!" % (
          field, cls.OP_DELIMITER))
    for part in parts:
      kv = part.split(cls.KV_DELIMITER, 1)
      if len(kv) != 2:
        if kv[0] == cls.OP_UNTAG and type.upper() == cls.TYPE_ACTION:
          ret['vlan_pop'] = True
          continue
        else:
          raise RuntimeError("Not a key-value pair: %s" % part)
      if kv[0] == cls.OP_INPORT:
        try:
          ret['in_port'] = int(kv[1])
        except ValueError:
          # self.log.warning(
          #    "in_port is not a valid port number: %s! Skip "
          #    "converting..." % kv[1])
          ret['in_port'] = kv[1]
      elif kv[0] == cls.OP_TAG:
        if type.upper() == cls.TYPE_MATCH:
          ret['vlan_id'] = kv[1].split(cls.LABEL_DELIMITER)[-1]
        elif type.upper() == cls.TYPE_ACTION:
          ret['vlan_push'] = kv[1].split(cls.LABEL_DELIMITER)[-1]
        else:
          raise RuntimeError('Not supported field type: %s!' % type)
      elif kv[0] == cls.OP_OUTPUT:
        ret['out'] = kv[1]
      elif kv[0] == cls.OP_FLOWCLASS and type.upper() == cls.TYPE_MATCH:
        ret['flowclass'] = kv[1]
      else:
        raise RuntimeError("Unrecognizable key: %s" % kv[0])
    return ret

  def _gen_unique_bb_id (self, v_node):
    """
    Generate a unique identifier based on original ID, delimiter and marker.

    :param v_node: virtualizer node object
    :return: unique ID
    :rtype: str
    """
    if self.__unique_bb_id and self.domain:
      return "%s%s%s" % (v_node.id.get_value(),
                         self.UNIQUE_ID_DELIMITER,
                         self.domain)
    else:
      return v_node.id.get_as_text()

  def _gen_unique_nf_id (self, v_vnf, bb_id=None):
    if self.__unique_nf_id:
      if bb_id is None:
        bb_id = self._gen_unique_bb_id(v_node=v_vnf.get_parent().get_parent())
      return "%s%s%s" % (v_vnf.id.get_value(),
                         self.UNIQUE_ID_DELIMITER,
                         bb_id)
    else:
      return v_vnf.id.get_as_text()

  def recreate_bb_id (self, id):
    """
    Recreate original ID based by removing trailing unique marker.

    :param id: unique id
    :type id: str
    :return: original ID
    :rtype: str
    """
    if self.__unique_bb_id:
      return str(id).rsplit(self.UNIQUE_ID_DELIMITER, 1)[0]
    else:
      return str(id)

  def recreate_nf_id (self, id):
    """
    Recreate original ID based by removing trailing unique marker.

    :param id: unique id
    :type id: str
    :return: original ID
    :rtype: str
    """
    if self.__unique_nf_id:
      return str(id).split(self.UNIQUE_ID_DELIMITER, 1)[0]
    else:
      return str(id)

  def _convert_flowrule_match (self, match):
    """
    Convert Flowrule match field from NFFG format to a unified format used by
    the Virtualizer.

    Based on Open vSwitch syntax:
    http://openvswitch.org/support/dist-docs/ovs-ofctl.8.txt

    :param match: flowrule match field
    :type match: str
    :return: converted data
    :rtype: str
    """
    # E.g.:  "match": "in_port=1;TAG=SAP1|comp|1" -->
    # E.g.:  "match": "in_port=SAP2|fwd|1;TAG=SAP1|comp|1" -->
    # <match>(in_port=1)dl_tag=1</match>
    ret = []
    match_part = match.split(';')
    if len(match_part) < 2:
      if not match_part[0].startswith("in_port"):
        self.log.warning("Invalid match field: %s" % match)
      return
    for kv in match_part:
      op = kv.split('=', 1)
      if op[0] not in self.GENERAL_OPERATIONS:
        self.log.warning("Unsupported match operand: %s" % op[0])
        continue
      if op[0] == self.OP_TAG:
        try:
          vlan_tag = int(op[1].split('|')[-1])
          ret.append("%s=%s" % (self.MATCH_TAG, format(vlan_tag, '#06x')))
        except ValueError:
          self.log.warning(
            "Wrong VLAN format: %s!" % op[1])
          continue
          # elif op[0] == self.OP_SGHOP:
          #   ret.append(kv)
      elif op[0] == self.OP_FLOWCLASS:
        ret.append(op[1])

    return self.OP_DELIMITER.join(ret)

  def _convert_flowrule_action (self, action):
    """
    Convert Flowrule action field from NFFG format to a unified format used by
    the Virtualizer.

    Based on Open vSwitch syntax:
    http://openvswitch.org/support/dist-docs/ovs-ofctl.8.txt

    :param action: flowrule action field
    :type action: str
    :return: converted data
    :rtype: str
    """
    # E.g.:  "action": "output=2;UNTAG"
    ret = []
    action_part = action.split(';')
    if len(action_part) < 2:
      if not action_part[0].startswith("output"):
        self.log.warning("Invalid action field: %s" % action)
      return
    for kv in action_part:
      op = kv.split('=')
      if op[0] not in self.GENERAL_OPERATIONS:
        # self.log.warning("Unsupported action operand: %s" % op[0])
        # return
        self.log.debug("Explicit action operand detected: %s" % op[0])
        ret.append(kv)
        continue
      if op[0] == self.OP_TAG:
        # E.g.: <action>push_tag:0x0037</action>
        try:
          vlan = int(op[1].split('|')[-1])
          ret.append("%s:%s" % (self.ACTION_PUSH_TAG, format(vlan, '#06x')))
        except ValueError:
          self.log.warning(
            "Wrong VLAN format: %s! Skip flowrule conversion..." % op[1])
          continue
      elif op[0] == self.OP_UNTAG:
        # E.g.: <action>strip_vlan</action>
        ret.append(self.ACTION_POP_TAG)
    return self.OP_DELIMITER.join(ret)

  def _parse_virtualizer_node_ports (self, nffg, infra, vnode):
    """
    Parse ports from a Virtualizer node into an :any:`NodeInfra` node.

    :param nffg: Container NFFG
    :type nffg: :class:`NFFG`
    :param infra: infrastructure node
    :type infra: :any:`NodeInfra`
    :param vnode: Virtualizer node
    :type vnode: Infra_node
    :return: None
    """
    # Add ports to Infra Node
    for vport in vnode.ports:
      # If it is a port connected to a SAP: <port-type>port-sap</port-type>
      if vport.port_type.get_value() == self.TYPE_VIRTUALIZER_PORT_SAP:
        # If inter-domain SAP -> id = <sap> tag: <sap>SAP14</sap>
        if vport.sap.is_initialized() and vport.sap.get_value():
          # Use unique SAP tag as the id of the SAP
          sap_id = vport.sap.get_value()  # Optional port.sap
          self.log.debug("Detected SAP id from sap field: %s" % sap_id)
        # Regular SAP
        elif vport.id.get_as_text().startswith(self.SAP_NAME_PREFIX):
          # port.id is mandatory now
          # Use port name as the SAP.id if it is set else generate one
          # SAP.id <--> virtualizer.node.port.id
          sap_id = vport.id.get_value()
          self.log.debug("Detected SAP id as id field: %s" % sap_id)
        # SAP.id <--> virtualizer.node.port.name
        elif vport.name.is_initialized() and \
           vport.name.get_as_text().upper().startswith(
             self.SAP_NAME_PREFIX + ":"):
          sap_id = vport.name.get_as_text()[len(self.SAP_NAME_PREFIX + ":"):]
          self.log.debug("Detected SAP id from name field: %s" % sap_id)
        elif vport.name.is_initialized() and \
           vport.name.get_as_text().upper().startswith(self.SAP_NAME_PREFIX):
          sap_id = vport.name.get_as_text()
          self.log.debug("Detected SAP id as name field: %s" % sap_id)
        else:
          # Backup SAP id generation
          # sap_id = "SAP%s" % len([s for s in nffg.saps])
          sap_id = "%s" % vport.id.get_value()
          self.log.debug(
            "No explicit SAP id was detected! Generated: %s" % sap_id)

        # Add port names
        if vport.name.is_initialized():
          sap_prefix = "%s:" % self.SAP_NAME_PREFIX
          if vport.name.get_as_text().startswith(sap_prefix):
            sap_name = vport.name.get_as_text()[len(sap_prefix):]
          else:
            sap_name = vport.name.get_as_text()
        else:
          sap_name = sap_id

        # Create SAP and Add port to SAP
        sap = nffg.add_sap(id=sap_id, name=sap_name)
        self.log.debug("Created SAP node: %s" % sap)

        try:
          # Use port id of the Infra node as the SAP port id
          # because sap port info was lost during NFFG->Virtualizer conversion
          sap_port_id = int(vport.id.get_value())  # Mandatory port.id
        except ValueError:
          sap_port_id = vport.id.get_value()
        sap_port = sap.add_port(id=sap_port_id)
        self.log.debug("Added SAP port: %s" % sap_port)

        # Add port properties as metadata to SAP port
        if vport.sap.is_initialized():
          # Add sap value to properties to be backward compatible for adaptation
          # layer
          sap_port.add_property("type", "inter-domain")
          sap_port.add_property("sap", vport.sap.get_value())
          sap_port.sap = str(vport.sap.get_value())

        # Create and add the port of the opposite Infra node
        try:
          infra_port_id = int(vport.id.get_value())
        except ValueError:
          infra_port_id = vport.id.get_value()
        # Add port to Infra
        infra_port = infra.add_port(id=infra_port_id)
        self.log.debug("Added infra port: %s" % infra_port)
        if vport.sap.is_initialized():
          # For internal use and backward compatibility
          infra_port.add_property("sap", vport.sap.get_value())
          infra_port.sap = vport.sap.get_value()

        # Add port names
        if vport.name.is_initialized():
          sap_port.name = infra_port.name = vport.name.get_as_text()

        # Fill SAP-specific data
        # Add infra port capabilities
        if vport.capability.is_initialized():
          sap_port.capability = infra_port.capability = \
            vport.capability.get_value()
          self.log.debug("Added capability: %s" % sap_port.capability)
        if vport.sap_data.is_initialized():
          if vport.sap_data.technology.is_initialized():
            sap_port.technology = infra_port.technology = \
              vport.sap_data.technology.get_value()
            self.log.debug("Added technology: %s" % sap_port.technology)
          if vport.sap_data.role.is_initialized():
            sap_port.role = infra_port.role = vport.sap_data.role.get_value()
            self.log.debug("Added role: %s" % sap_port.role)
          if vport.sap_data.resources.is_initialized():
            if vport.sap_data.resources.delay.is_initialized():
              try:
                sap_port.delay = infra_port.delay = float(
                  vport.sap_data.resources.delay.get_value())
              except ValueError:
                sap_port.delay = infra_port.delay = \
                  vport.sap_data.resources.delay.get_value()
              self.log.debug("Added delay: %s" % sap_port.delay)
            if vport.sap_data.resources.bandwidth.is_initialized():
              try:
                sap_port.bandwidth = infra_port.bandwidth = float(
                  vport.sap_data.resources.bandwidth.get_value())
              except ValueError:
                sap_port.bandwidth = infra_port.bandwidth = \
                  vport.sap_data.resources.bandwidth.get_value()
              self.log.debug("Added bandwidth: %s" % sap_port.bandwidth)
            if vport.sap_data.resources.cost.is_initialized():
              try:
                sap_port.cost = infra_port.cost = float(
                  vport.sap_data.resources.cost.get_value())
              except ValueError:
                sap_port.cost = infra_port.cost = \
                  vport.sap_data.resources.cost.get_value()
              self.log.debug("Added cost: %s" % sap_port.cost)
            if vport.sap_data.resources.qos.is_initialized():
              try:
                sap_port.qos = infra_port.qos = \
                  vport.sap_data.resources.qos.get_value()
              except ValueError:
                sap_port.qos = infra_port.qos = \
                  vport.sap_data.resources.qos.get_value()
              self.log.debug("Added qos: %s" % sap_port.qos)
        if vport.control.is_initialized():
          sap_port.controller = infra_port.controller = \
            vport.control.controller.get_value()
          self.log.debug("Added controller: %s" % sap_port.controller)
          sap_port.orchestrator = infra_port.orchestrator = \
            vport.control.orchestrator.get_value()
          self.log.debug("Added orchestrator: %s" % sap_port.orchestrator)
        if vport.addresses.is_initialized():
          self.log.debug("Translate addresses...")
          sap_port.l2 = infra_port.l2 = vport.addresses.l2.get_value()
          sap_port.l4 = infra_port.l4 = vport.addresses.l4.get_value()
          for l3 in vport.addresses.l3.itervalues():
            sap_port.l3.add_l3address(id=l3.id.get_value(),
                                      name=l3.name.get_value(),
                                      configure=l3.configure.get_value(),
                                      client=l3.client.get_value(),
                                      requested=l3.requested.get_value(),
                                      provided=l3.provided.get_value())
            infra_port.l3.add_l3address(id=l3.id.get_value(),
                                        name=l3.name.get_value(),
                                        configure=l3.configure.get_value(),
                                        client=l3.client.get_value(),
                                        requested=l3.requested.get_value(),
                                        provided=l3.provided.get_value())
        # Add metadata from infra port metadata to sap metadata
        for key in vport.metadata:  # Optional - port.metadata
          sap_port.add_metadata(name=key,
                                value=vport.metadata[key].value.get_value())
          infra_port.add_metadata(name=key,
                                  value=vport.metadata[key].value.get_value())
        self.log.debug("Added port for SAP -> %s" % infra_port)
        # Add connection between infra - SAP
        # SAP-Infra is static link --> create link for both direction
        l1, l2 = nffg.add_undirected_link(
          p1p2id="%s-%s-link" % (sap_id, infra.id),
          p2p1id="%s-%s-link-back" % (sap_id, infra.id),
          port1=sap_port,
          port2=infra_port,
          delay=sap_port.delay,
          bandwidth=sap_port.bandwidth,
          cost=sap_port.cost, qos=sap_port.qos)
        # Handle operation tag
        if vport.get_operation() is not None:
          self.log.debug("Found operation tag: %s for port: %s" % (
            vport.get_operation(), vport.id.get_value()))
          sap.operation = vport.get_operation()
          sap_port.operation = vport.get_operation()
          # l1.operation = vport.get_operation()
          # l2.operation = vport.get_operation()

        self.log.debug("Added SAP-Infra connection: %s" % l1)
        self.log.debug("Added Infra-SAP connection: %s" % l2)

      # If it is not SAP port and probably connected to another infra
      elif vport.port_type.get_value() == self.TYPE_VIRTUALIZER_PORT_ABSTRACT:
        # Add Infra port
        try:
          infra_port_id = int(vport.id.get_value())
        except ValueError:
          infra_port_id = vport.id.get_value()
        # Add port properties as property to Infra port
        infra_port = infra.add_port(id=infra_port_id)
        self.log.debug("Added infra port: %s" % infra_port)
        self.__copy_vport_attrs(port=infra_port, vport=vport)
        self.log.debug("Added static %s" % infra_port)
      else:
        self.log.warning("Port type is not defined for port: %s " % vport)

  def _parse_virtualizer_node_nfs (self, nffg, infra, vnode):
    """
    Parse VNFs from a Virtualizer nodes into :any:`NodeNF` list.

    :param nffg: Container NFFG
    :type nffg: :class:`NFFG`
    :param infra: infrastructure node
    :type infra: :any:`NodeInfra`
    :param vnode: Virtualizer node
    :type vnode: Infra_node
    :return: None
    """
    # Create NF instances
    for v_vnf in vnode.NF_instances:
      # Get NF params
      nf_id = self._gen_unique_nf_id(v_vnf=v_vnf, bb_id=infra.id)  # Mandatory
      nf_name = v_vnf.name.get_value()  # Optional - nf.name, default = None
      nf_ftype = v_vnf.type.get_value()  # Optional - nf.type, default = None
      # No deployment_type in Virtualizer try to get if from metadata
      if 'deployment_type' in v_vnf.metadata.keys():
        nf_dep_type = v_vnf.metadata['deployment_type'].value.get_value()
      else:
        nf_dep_type = None
      # Add NF resources, remove optional units
      if v_vnf.resources.is_initialized():
        if v_vnf.resources.cpu.is_initialized():
          nf_cpu = v_vnf.resources.cpu.get_as_text().split(' ')[0]
        else:
          nf_cpu = None
        if v_vnf.resources.mem.is_initialized():
          nf_mem = v_vnf.resources.mem.get_as_text().split(' ')[0]
        else:
          nf_mem = None
        if v_vnf.resources.storage.is_initialized():
          nf_storage = v_vnf.resources.storage.get_as_text().split(' ')[0]
        else:
          nf_storage = None
        if v_vnf.resources.cost.is_initialized():
          nf_cost = v_vnf.resources.cost.get_as_text().split(' ')[0]
        else:
          nf_cost = None
        try:
          nf_cpu = float(nf_cpu) if nf_cpu is not None else None
        except ValueError as e:
          self.log.warning("Resource cpu value is not valid number: %s" % e)
        try:
          nf_mem = float(nf_mem) if nf_mem is not None else None
        except ValueError as e:
          self.log.warning("Resource mem value is not valid number: %s" % e)
        try:
          nf_storage = float(nf_storage) if nf_storage is not None else None
        except ValueError as e:
          self.log.warning(
            "Resource storage value is not valid number: %s" % e)
        try:
          nf_cost = float(nf_cost) if nf_cost is not None else None
        except ValueError as e:
          self.log.warning(
            "Resource cost value is not valid number: %s" % e)
      else:
        nf_cpu = nf_mem = nf_storage = nf_cost = None
      # Get remained NF resources from metadata
      if 'delay' in v_vnf.metadata.keys():
        nf_delay = v_vnf.metadata['delay'].value.get_value()
      else:
        nf_delay = None
      if 'bandwidth' in v_vnf.metadata.keys():
        nf_bandwidth = v_vnf.metadata['bandwidth'].value.get_value()
      else:
        nf_bandwidth = None
      # Create NodeNF
      nf = nffg.add_nf(id=nf_id, name=nf_name, func_type=nf_ftype,
                       dep_type=nf_dep_type, cpu=nf_cpu, mem=nf_mem,
                       storage=nf_storage, delay=nf_delay, cost=nf_cost,
                       bandwidth=nf_bandwidth)
      if v_vnf.status.is_initialized():
        nf.status = v_vnf.status.get_value()

      self.log.debug("Created NF: %s" % nf)

      self.log.debug("Parse NF constraints...")
      if v_vnf.constraints.is_initialized():
        # Add affinity list
        if v_vnf.constraints.affinity.is_initialized():
          for aff in v_vnf.constraints.affinity.values():
            try:
              aff_id = self._gen_unique_nf_id(v_vnf=aff.object.get_target())
              aff = nf.constraints.add_affinity(id=aff.id.get_value(),
                                                value=aff_id)
              self.log.debug("Add affinity: %s to %s" % (aff, nf.id))
            except StandardError as e:
              self.log.exception(
                "Skip affinity conversion due to error: %s" % e)
        # Add antiaffinity list
        if v_vnf.constraints.antiaffinity.is_initialized():
          for naff in v_vnf.constraints.antiaffinity.values():
            try:
              naff_id = self._gen_unique_nf_id(v_vnf=naff.object.get_target(),
                                               bb_id=infra.id)
              naff = nf.constraints.add_antiaffinity(id=naff.id.get_value(),
                                                     value=naff_id)
              self.log.debug("Add antiaffinity: %s to %s" % (naff, nf.id))
            except StandardError as e:
              self.log.exception(
                "Skip anti-affinity conversion due to error: %s" % e)
        # Add variables dict
        if v_vnf.constraints.variable.is_initialized():
          for var in v_vnf.constraints.variable.values():
            try:
              var_id = self._gen_unique_nf_id(v_vnf=var.object.get_target(),
                                              bb_id=infra.id)
              var = nf.constraints.add_variable(key=var.id.get_value(),
                                                id=var_id)
              self.log.debug("Add variable: %s to %s" % (var, nf.id))
            except StandardError as e:
              self.log.exception(
                "Skip variable conversion due to error: %s" % e)
        # Add constraint list
        if v_vnf.constraints.constraint.is_initialized():
          for constraint in v_vnf.constraints.constraint.values():
            try:
              formula = nf.constraints.add_constraint(
                id=constraint.id.get_value(),
                formula=constraint.formula.get_value())
              self.log.debug("Add constraint: %s to %s" % (formula, nf.id))
            except StandardError as e:
              self.log.exception(
                "Skip constraint conversion due to error: %s" % e)
        if v_vnf.constraints.restorability.is_initialized():
          nf.constraints.restorability = \
            v_vnf.constraints.restorability.get_as_text()
          self.log.debug("Add restorability: %s to %s"
                         % (nf.constraints.restorability, nf.id))

      # Add NF metadata
      for key in v_vnf.metadata:
        if key not in ('delay', 'bandwidth'):
          nf.add_metadata(name=key,
                          value=v_vnf.metadata[key].value.get_value())

      # Handle operation tag
      if v_vnf.get_operation() is not None:
        self.log.debug("Found operation tag: %s for NF: %s" % (
          v_vnf.get_operation(), v_vnf.id.get_value()))
        nf.operation = v_vnf.get_operation()

      # Create NF ports
      for vport in v_vnf.ports:
        # Add VNF port
        try:
          nf_port_id = int(vport.id.get_value())
        except ValueError:
          nf_port_id = vport.id.get_value()
        # Create and Add port
        nf_port = nf.add_port(id=nf_port_id)
        # Fill SAP-specific data
        # Add port properties
        if vport.name.is_initialized():
          nf_port.name = vport.name.get_value()
        # Store specific SAP port in NFs transparently
        if vport.port_type.is_initialized():
          if vport.sap.is_initialized():
            nf_port.sap = vport.sap.get_value()
        else:
          self.log.warning("Port type is missing from node: %s" % vport.id)
        # Add infra port capabilities
        if vport.capability.is_initialized():
          nf_port.capability = vport.capability.get_value()
        if vport.sap_data.is_initialized():
          if vport.sap_data.technology.is_initialized():
            nf_port.technology = vport.sap_data.technology.get_value()
          if vport.sap_data.role.is_initialized():
            nf_port.role = vport.sap_data.role.get_value()
          if vport.sap_data.resources.is_initialized():
            if vport.sap_data.resources.delay.is_initialized():
              try:
                nf_port.delay = float(
                  vport.sap_data.resources.delay.get_value())
              except ValueError:
                nf_port.delay = vport.sap_data.resources.delay.get_value()
            if vport.sap_data.resources.bandwidth.is_initialized():
              try:
                nf_port.bandwidth = float(
                  vport.sap_data.resources.bandwidth.get_value())
              except ValueError:
                nf_port.bandwidth = \
                  vport.sap_data.resources.bandwidth.get_value()
            if vport.sap_data.resources.cost.is_initialized():
              try:
                nf_port.cost = float(
                  vport.sap_data.resources.cost.get_value())
              except ValueError:
                nf_port.cost = vport.sap_data.resources.cost.get_value()
        if vport.control.is_initialized():
          if vport.control.controller.is_initialized():
            nf_port.controller = vport.control.controller.get_value()
          if vport.control.orchestrator.is_initialized():
            nf_port.orchestrator = vport.control.orchestrator.get_value()
        if vport.addresses.is_initialized():
          nf_port.l2 = vport.addresses.l2.get_value()
          nf_port.l4 = vport.addresses.l4.get_value()
          for l3 in vport.addresses.l3.itervalues():
            nf_port.l3.add_l3address(id=l3.id.get_value(),
                                     name=l3.name.get_value(),
                                     configure=l3.configure.get_value(),
                                     client=l3.client.get_value(),
                                     requested=l3.requested.get_value(),
                                     provided=l3.provided.get_value())
        # Add port metadata
        for key in vport.metadata:
          nf_port.add_metadata(name=key,
                               value=vport.metadata[key].value.get_value())
        # VNF port can not be a SAP port -> skip <port_type> saving
        # VNF port can not be a SAP port -> skip <sap> saving

        # Handle operation tag
        if vport.get_operation() is not None:
          self.log.debug("Found operation tag: %s for port: %s" % (
            vport.get_operation(), vport.id.get_value()))
          nf_port.operation = vport.get_operation()

        self.log.debug("Added NF port: %s" % nf_port)

        # Add connection between Infra - NF
        # Infra - NF port on Infra side is always a dynamically generated port
        dyn_port = self.LABEL_DELIMITER.join((infra.id,
                                              nf_id,
                                              vport.id.get_as_text()))
        # Add Infra-side port
        infra_port = infra.add_port(id=dyn_port)
        self.log.debug("Added dynamic port for NF -> %s" % infra_port)

        # NF-Infra is dynamic link --> create special undirected link
        l1, l2 = nffg.add_undirected_link(port1=nf_port,
                                          port2=infra_port,
                                          dynamic=True)
        self.log.debug("Added dynamic VNF-Infra connection: %s" % l1)
        self.log.debug("Added dynamic Infra-VNF connection: %s" % l2)

  @staticmethod
  def __parse_external_port (flowentry):
    """

    :param flowentry:
    :return: (domain name, node id, port id)
    """
    res = re.match(r"(.*)://.*node\[id=(.*?)\].*port\[id=(.*?)\].*", flowentry)
    if len(res.groups()) != 3:
      log.error("Missing id from external flowrule: %s" % flowentry)
      return None, None, None
    return res.groups()

  def _parse_virtualizer_node_flowentries (self, nffg, infra, vnode):
    """
    Parse FlowEntries from a Virtualizer Node into an :any:`InfraPort`.

    :param nffg: Container NFFG
    :type nffg: :class:`NFFG`
    :param infra: infrastructure node
    :type infra: :any:`NodeInfra`
    :param vnode: Virtualizer node
    :type vnode: Infra_node
    :return: None
    """
    # Create Flowrules
    for flowentry in vnode.flowtable:
      vport = vport_id = None
      fr_external = False
      fr_id = flowentry.id.get_value()  # Mandatory flowentry.id
      try:
        fr_id = int(fr_id)
      except ValueError:
        self.log.error("Parsed flowentry id is not valid integer!")
        continue

      # e.g. in_port=1(;TAG=SAP1|comp|1)
      fr_match = "in_port="
      if not flowentry.port.is_initialized():
        self.log.error("Port attribute is missing from flowrule:\n%s"
                       % flowentry.xml())
        continue
      # Check if the in port is an external port (that does not exist)
      if "://" in flowentry.port.get_as_text():
        self.log.debug("Detected external in port reference: %s"
                       % flowentry.port.get_as_text())
        # Mark flowrule as external so SG recreation can skip it
        fr_external = True
        ext_domain, ext_node, ext_port = self.__parse_external_port(
          flowentry.port.get_value())
        vport_id = "EXTERNAL:%s" % ext_port
        bb_node = nffg[self._gen_unique_bb_id(vnode)]
        if vport_id in bb_node.ports:
          self.log.debug("External port: %s already exits! Skip creating..."
                         % vport_id)
          vport = bb_node.ports[vport_id]
        else:
          vport = bb_node.add_port(id=vport_id)
          self.log.debug("Added external in port: %s" % vport)
          # Mark dynamic port as external for later processing
          try:
            ext_port = int(ext_port)
          except ValueError:
            pass
          vport.role = "EXTERNAL"
          vport.add_property("domain", ext_domain)
          vport.add_property("node", ext_node)
          vport.add_property("port", ext_port)
          vport.add_property("path", flowentry.port.get_as_text())
        fr_match += vport_id
        # Add SAP to request
        if vport_id in nffg and vport_id in nffg[vport_id].ports:
          # SAP with port already exist
          if nffg[vport_id].ports[vport_id].role != "EXTERNAL":
            self.log.error("SAP: %s already exists but it is not an external "
                           "SAP!" % nffg[vport_id].ports[vport_id])
          else:
            self.log.debug("External SAP: %s already exists! Skip creation..."
                           % nffg[vport_id].ports[vport_id])
        else:
          ext_sap = nffg.add_sap(id=vport_id)
          ext_sap_port = ext_sap.add_port(id=vport_id)
          ext_sap_port.role = "EXTERNAL"
          ext_sap_port.add_property("path", flowentry.port.get_as_text())
          nffg.add_undirected_link(port1=vport, port2=ext_sap_port)
          self.log.debug("Created external SAP: %s" % ext_sap)
        # Set v_fe_port for further use
        v_fe_port = None
      else:
        try:
          v_fe_port = flowentry.port.get_target()
        except StandardError:
          self.log.exception("Got unexpected exception during acquisition of "
                             "IN Port in Flowentry: %s!" % flowentry.xml())
          continue
        # Check if src port is a VNF port --> create the tagged port name
        if "NF_instances" in flowentry.port.get_as_text():
          v_src_nf = v_fe_port.get_parent().get_parent()
          v_src_node = v_src_nf.get_parent().get_parent()
          # Add domain name to the node id if unique_id is set
          src_node = self._gen_unique_bb_id(v_src_node)
          src_nf = self._gen_unique_nf_id(v_vnf=v_src_nf, bb_id=infra.id)
          fr_match += self.LABEL_DELIMITER.join((src_node, src_nf,
                                                 v_fe_port.id.get_as_text()))
        else:
          # Else just Infra port --> add only the port number
          fr_match += v_fe_port.id.get_as_text()

      # Pre-check target-less dst port flowrule
      fr_action = "output="
      if not flowentry.out.is_initialized():
        self.log.error("Out attribute is missing from flowrule:\n%s"
                       % flowentry.xml())
        continue
      if "://" in flowentry.out.get_as_text():
        self.log.debug("Detected external out port reference: %s"
                       % flowentry.out.get_as_text())
        # Mark flowrule as external so SG recreation can skip it
        fr_external = True
        ext_domain, ext_node, ext_port = self.__parse_external_port(
          flowentry.out.get_value())
        ext_port_id = "EXTERNAL:%s" % ext_port
        bb_node = nffg[self._gen_unique_bb_id(vnode)]
        if ext_port_id in bb_node.ports:
          self.log.debug("External port: %s already exits! Skip creating..." %
                         ext_port_id)
          ext_vport = bb_node.ports[ext_port_id]
        else:
          ext_vport = bb_node.add_port(id=ext_port_id)
          self.log.debug("Added external out port: %s" % ext_vport)
          # Mark dynamic port as external for later processing
          try:
            ext_port = int(ext_port)
          except ValueError:
            pass
          ext_vport.role = "EXTERNAL"
          # ext_vport.sap = ext_port
          ext_vport.add_property("domain", ext_domain)
          ext_vport.add_property("node", ext_node)
          ext_vport.add_property("port", ext_port)
          ext_vport.add_property("path", flowentry.out.get_as_text())
        fr_action += ext_port_id
        # Add SAP to request
        if ext_port_id in nffg and ext_port_id in nffg[ext_port_id].ports:
          # SAP with port already exist
          if nffg[ext_port_id].ports[ext_port_id].role != "EXTERNAL":
            self.log.error("SAP: %s already exists but it is not an external "
                           "SAP!" % nffg[ext_port_id].ports[ext_port_id])
          else:
            self.log.debug("External SAP: %s already exists! Skip creating..."
                           % nffg[ext_port_id].ports[ext_port_id])
        else:
          ext_sap = nffg.add_sap(id=ext_port_id)
          ext_sap_port = ext_sap.add_port(id=ext_port_id)
          ext_sap_port.role = "EXTERNAL"
          ext_sap_port.add_property("path", flowentry.out.get_as_text())
          nffg.add_undirected_link(port1=ext_vport, port2=ext_sap_port)
          self.log.debug("Created external SAP: %s" % ext_sap)
        # Set v_fe_out for further use
        v_fe_out = None
      else:
        try:
          v_fe_out = flowentry.out.get_target()
        except StandardError:
          self.log.exception(
            "Got unexpected exception during acquisition of OUT "
            "Port in Flowentry: %s!" % flowentry.xml())
          continue
        # Check if dst port is a VNF port --> create the tagged port name
        if "NF_instances" in flowentry.out.get_as_text():
          v_dst_nf = v_fe_out.get_parent().get_parent()
          v_dst_node = v_dst_nf.get_parent().get_parent()
          dst_node = self._gen_unique_bb_id(v_dst_node)
          dst_nf = self._gen_unique_nf_id(v_vnf=v_dst_nf, bb_id=infra.id)
          fr_action += self.LABEL_DELIMITER.join((dst_node, dst_nf,
                                                  v_fe_out.id.get_as_text()))
        else:
          # Else just Infra port --> add only the port number
          fr_action += v_fe_out.id.get_as_text()

      # Check if there is a matching operation -> currently just TAG is used
      if flowentry.match.is_initialized() and flowentry.match.get_value():
        for op in flowentry.match.get_as_text().split(self.OP_DELIMITER):
          if op.startswith(self.OP_INPORT):
            pass
          # e.g. <match>dl_tag=0x0004</match> --> in_port=1;TAG=SAP2|fwd|4
          elif op.startswith(self.MATCH_TAG):
            # if src or dst was a SAP: SAP.id == port.name
            # if scr or dst is a VNF port name of parent of port
            if v_fe_port is None:
              _src_name = "external"
            elif v_fe_port.port_type.get_as_text() == \
               self.TYPE_VIRTUALIZER_PORT_SAP:
              # If port is an inter-domain SAP port --> port.sap
              if v_fe_port.sap.is_initialized() and v_fe_port.sap.get_value():
                _src_name = v_fe_port.sap.get_as_text()
              # If port is local SAP --> SAP:<sap_name>
              elif v_fe_port.name.is_initialized() and str(
                 v_fe_port.name.get_value()).startswith(self.SAP_NAME_PREFIX):
                _src_name = v_fe_port.name.get_as_text()[
                            len(self.SAP_NAME_PREFIX + ":"):]
              else:
                _src_name = str(v_fe_port.name.get_value())
            else:
              _src_name = v_fe_port.get_parent().get_parent().id.get_as_text()
            # If port is an inter-domain SAP port --> port.sap
            if v_fe_out is None:
              _dst_name = "external"
            elif v_fe_out.port_type.get_as_text() == \
               self.TYPE_VIRTUALIZER_PORT_SAP:
              # If port is an inter-domain SAP port --> port.sap
              if v_fe_out.sap.is_initialized() and v_fe_out.sap.get_value():
                _dst_name = v_fe_out.sap.get_as_text()
              # If port is local SAP --> SAP:<sap_name>
              elif v_fe_out.name.is_initialized() and str(
                 v_fe_out.name.get_value()).startswith(self.SAP_NAME_PREFIX):
                _dst_name = v_fe_out.name.get_as_text()[
                            len(self.SAP_NAME_PREFIX + ':'):]
              else:
                _dst_name = v_fe_out.name.get_as_text()
            else:
              _dst_name = v_fe_out.get_parent().get_parent().id.get_as_text()
            # Convert from int/hex to int
            _tag = int(op.split('=')[1], base=0)
            fr_match += ";%s=%s" % (self.OP_TAG, self.LABEL_DELIMITER.join(
              (_src_name, _dst_name, str(_tag))))
          else:
            # Everything else is must come from flowclass
            fr_match += ";%s=%s" % (self.OP_FLOWCLASS, op)

      # Check if there is an action operation
      if flowentry.action.is_initialized() and flowentry.action.get_value():
        for op in flowentry.action.get_as_text().split(self.OP_DELIMITER):
          # e.g. <action>push_tag:0x0003</action> -->
          # output=1;TAG=decomp|SAP2|3
          if op.startswith(self.ACTION_PUSH_TAG):
            # tag: src element name | dst element name | tag
            # if src or dst was a SAP: SAP.id == port.name
            # if scr or dst is a VNF port name of parent of port
            if v_fe_port is None:
              _src_name = "external"
            elif v_fe_port.port_type.get_as_text() == \
               self.TYPE_VIRTUALIZER_PORT_SAP:
              # If port is an inter-domain SAP port --> port.sap
              if v_fe_port.sap.is_initialized() and v_fe_port.sap.get_value():
                _src_name = v_fe_port.sap.get_as_text()
              # If port is local SAP --> SAP:<sap_name>
              elif v_fe_port.name.is_initialized() and str(
                 v_fe_port.name.get_value()).startswith(self.SAP_NAME_PREFIX):
                _src_name = v_fe_port.name.get_as_text()[
                            len(self.SAP_NAME_PREFIX + ':'):]
              else:
                _src_name = v_fe_port.name.get_as_text()
            else:
              _src_name = v_fe_port.get_parent().get_parent().id.get_as_text()
            if v_fe_out is None:
              _dst_name = "external"
            elif v_fe_out.port_type.get_as_text() == \
               self.TYPE_VIRTUALIZER_PORT_SAP:
              # If port is an inter-domain SAP port --> port.sap
              if v_fe_out.sap.is_initialized() and v_fe_out.sap.get_value():
                _dst_name = v_fe_out.sap.get_as_text()
              elif v_fe_out.name.is_initialized() and str(
                 v_fe_out.name.get_value()).startswith(self.SAP_NAME_PREFIX):
                _dst_name = v_fe_out.name.get_as_text()[
                            len(self.SAP_NAME_PREFIX + ':'):]
              else:
                _dst_name = v_fe_out.name.get_as_text()
            else:
              _dst_name = v_fe_out.get_parent().get_parent().id.get_as_text()
            # Convert from int/hex to int
            _tag = int(op.split(':')[1], base=0)
            fr_action += ";%s=%s" % (self.OP_TAG, self.LABEL_DELIMITER.join(
              (_src_name, _dst_name, str(_tag))))
          # e.g. <action>strip_vlan</action> --> output=EE2|fwd|1;UNTAG
          elif op.startswith(self.ACTION_POP_TAG):
            fr_action += ";%s" % self.OP_UNTAG
          else:
            fr_action += ";%s" % op

      # Get the src (port where fr need to store) and dst port id
      if vport_id is None:
        try:
          vport_id = int(v_fe_port.id.get_value())
        except ValueError:
          vport_id = v_fe_port.id.get_value()

      # Get port from NFFG in which need to store the fr
      if vport is None:
        try:
          # If the port is an Infra port
          if "NF_instances" not in flowentry.port.get_as_text():
            vport = nffg[infra.id].ports[vport_id]
          # If the port is a VNF port -> get the dynamic port in the Infra
          else:
            _vnf_id = self._gen_unique_nf_id(
              v_vnf=v_fe_port.get_parent().get_parent(), bb_id=infra.id)
            _dyn_port = [l.dst.id for u, v, l in
                         nffg.network.edges_iter([_vnf_id], data=True) if
                         l.type == NFFG.TYPE_LINK_DYNAMIC and str(l.src.id) ==
                         str(vport_id)]
            if len(_dyn_port) > 1:
              self.log.warning("Multiple dynamic link detected for NF(id: %s) "
                               "Use first link ..." % _vnf_id)
            elif len(_dyn_port) < 1:
              raise RuntimeError("Missing infra-vnf dynamic link for vnf: %s" %
                                 _vnf_id)
            # Get dynamic port from infra
            vport = nffg[infra.id].ports[_dyn_port[0]]
        except RuntimeError as e:
          self.log.error("Port: %s is not found in the NFFG: "
                         "%s from the flowrule:\n%s" %
                         (vport_id, e.message, flowentry.xml()))
          continue

      # Get resource values
      self.log.debug("Parse flowrule resources...")
      if flowentry.resources.is_initialized():
        if flowentry.resources.bandwidth.is_initialized():
          try:
            fr_bw = float(flowentry.resources.bandwidth.get_value())
          except ValueError:
            fr_bw = flowentry.resources.bandwidth.get_value()
        else:
          fr_bw = None
        if flowentry.resources.delay.is_initialized():
          try:
            fr_delay = float(flowentry.resources.delay.get_value())
          except ValueError:
            fr_delay = flowentry.resources.delay.get_value()
        else:
          fr_delay = None
        if flowentry.resources.cost.is_initialized():
          fr_cost = flowentry.resources.cost.get_value()
        else:
          fr_cost = None
        if flowentry.resources.qos.is_initialized():
          fr_qos = flowentry.resources.qos.get_value()
        else:
          fr_qos = None
      else:
        fr_bw = fr_delay = fr_cost = fr_qos = None

      # Add constraints
      self.log.debug("Parse flowrule constraints...")
      fr_constraints = Constraints()
      if flowentry.constraints.is_initialized():
        # Add affinity list
        if flowentry.constraints.affinity.is_initialized():
          for aff in flowentry.constraints.affinity.values():
            aff = fr_constraints.add_affinity(id=aff.id.get_value(),
                                              value=aff.object.get_value())
            self.log.debug("Add affinity: %s to %s" % (aff, fr_id))
        # Add antiaffinity list
        if flowentry.constraints.antiaffinity.is_initialized():
          for naff in flowentry.constraints.antiaffinity.values():
            naff = fr_constraints.add_antiaffinity(id=naff.id.get_value(),
                                                   value=naff.object.get_value())
            self.log.debug("Add antiaffinity: %s to %s" % (naff, fr_id))
        # Add variables dict
        if flowentry.constraints.variable.is_initialized():
          for var in flowentry.constraints.variable.values():
            var = fr_constraints.add_variable(key=var.id.get_value(),
                                              id=var.object.get_value())
            self.log.debug("Add variable: %s to %s" % (var, fr_id))
        # Add constraint list
        if flowentry.constraints.constraint.is_initialized():
          for constraint in flowentry.constraints.constraint.values():
            formula = fr_constraints.add_constraint(
              id=constraint.id.get_value(),
              formula=constraint.formula.get_value())
            self.log.debug("Add constraint: %s to %s" % (formula, fr_id))
        if flowentry.constraints.restorability.is_initialized():
          fr_constraints.restorability = \
            flowentry.constraints.restorability.get_as_text()
          self.log.debug("Add restorability: %s to %s"
                         % (fr_constraints.restorability, fr_id))

          # Add flowrule to port
      fr = vport.add_flowrule(id=fr_id, match=fr_match, action=fr_action,
                              bandwidth=fr_bw, delay=fr_delay, cost=fr_cost,
                              qos=fr_qos, external=fr_external,
                              constraints=fr_constraints)

      # Handle operation tag
      if flowentry.get_operation() is not None:
        self.log.debug("Found operation tag: %s for flowentry: %s" % (
          flowentry.get_operation(), flowentry.id.get_value()))
        fr.operation = flowentry.get_operation()

      self.log.debug("Added %s" % fr)

  def _parse_virtualizer_nodes (self, nffg, virtualizer):
    """
    Parse Infrastructure node from Virtualizer.

    :param nffg: Container NFFG
    :type nffg: :class:`NFFG`
    :param virtualizer: Virtualizer object
    :type virtualizer: Virtualizer
    :return: None
    """
    # Iterate over virtualizer/nodes --> node = Infra
    for vnode in virtualizer.nodes:
      # Node params
      # Add domain name to the node id if unique_id is set
      node_id = self._gen_unique_bb_id(vnode)
      if vnode.name.is_initialized():  # Optional - node.name
        node_name = vnode.name.get_value()
      else:
        node_name = None
      node_domain = self.domain  # Set domain as the domain of the Converter
      node_type = vnode.type.get_value()  # Mandatory - virtualizer.type
      # Node-resources params
      if vnode.resources.is_initialized():
        # Remove units and store the value only
        node_cpu = vnode.resources.cpu.get_as_text().split(' ')[0]
        node_mem = vnode.resources.mem.get_as_text().split(' ')[0]
        node_storage = vnode.resources.storage.get_as_text().split(' ')[0]
        node_cost = vnode.resources.cost.get_value()
        node_zone = vnode.resources.zone.get_value()
        try:
          node_cpu = float(node_cpu) if node_cpu is not None else None
        except ValueError as e:
          self.log.warning("Resource cpu value is not valid number: %s" % e)
        try:
          node_mem = float(node_mem) if node_mem is not None else None
        except ValueError as e:
          self.log.warning("Resource mem value is not valid number: %s" % e)
        try:
          node_storage = float(
            node_storage) if node_storage is not None else None
        except ValueError as e:
          self.log.warning("Resource storage value is not valid number: %s" % e)
      else:
        # Default value for cpu,mem,storage: None
        node_cpu = node_mem = node_storage = node_cost = node_zone = None
      # Try to get bw value from metadata
      if 'bandwidth' in vnode.metadata:
        # Converted to float in Infra constructor
        node_bw = vnode.metadata['bandwidth'].value.get_value()
      else:
        # Iterate over links to summarize bw value for infra node
        node_bw = [
          float(vlink.resources.bandwidth.get_value())
          for vlink in vnode.links if vlink.resources.is_initialized() and
                                      vlink.resources.bandwidth.is_initialized()]
        # Default value: None
        node_bw = min(node_bw) if node_bw else None
      try:
        if node_bw is not None:
          node_bw = float(node_bw)
      except ValueError as e:
        self.log.warning(
          "Resource bandwidth value is not valid number: %s" % e)
      if 'delay' in vnode.metadata:
        # Converted to float in Infra constructor
        node_delay = vnode.metadata['delay'].value.get_value()
      else:
        # Iterate over links to summarize delay value for infra node
        node_delay = [
          float(vlink.resources.delay.get_value())
          for vlink in vnode.links if vlink.resources.is_initialized() and
                                      vlink.resources.delay.is_initialized()]
        # Default value: None
        node_delay = max(node_delay) if node_delay else None
      try:
        if node_delay is not None:
          node_delay = float(node_delay)
      except ValueError as e:
        self.log.warning("Resource delay value is not valid number: %s" % e)
      # Add Infra Node to NFFG
      infra = nffg.add_infra(id=node_id, name=node_name, domain=node_domain,
                             infra_type=node_type, cpu=node_cpu, mem=node_mem,
                             cost=node_cost, zone=node_zone,
                             storage=node_storage, delay=node_delay,
                             bandwidth=node_bw)
      self.log.debug("Created INFRA node: %s" % infra)
      self.log.debug("Parsed resources: %s" % infra.resources)
      for vlink in vnode.links:
        if vlink.resources.is_initialized() and \
           vlink.resources.delay.is_initialized():
          try:
            dm_src = vlink.src.get_target().id.get_value()
            dm_dst = vlink.dst.get_target().id.get_value()
          except StandardError:
            self.log.exception(
              "Got unexpected exception during acquisition of src/dst "
              "Port in Link: %s!" % vlink.xml())
            continue
          dm_delay = float(vlink.resources.delay.get_value())
          infra.delay_matrix.add_delay(src=dm_src, dst=dm_dst, delay=dm_delay)
          self.log.debug("Added delay: %s to delay matrix [%s --> %s]"
                         % (dm_delay, dm_src, dm_dst))

      # Add supported types shrinked from the supported NF list
      for sup_nf in vnode.capabilities.supported_NFs:
        infra.add_supported_type(sup_nf.type.get_value())

      # Handle operation tag
      if vnode.get_operation() is not None:
        self.log.debug("Found operation tag: %s for node: %s" % (
          vnode.get_operation(), vnode.id.get_value()))
        infra.operation = vnode.get_operation()

      # Parse Ports
      self._parse_virtualizer_node_ports(nffg=nffg, infra=infra, vnode=vnode)

      # Parse NF_instances
      self._parse_virtualizer_node_nfs(nffg=nffg, infra=infra, vnode=vnode)

      # Parse Flowentries
      self._parse_virtualizer_node_flowentries(nffg=nffg, infra=infra,
                                               vnode=vnode)

      self.log.debug("Parse INFRA node constraints...")
      if vnode.constraints.is_initialized():
        # Add affinity list
        if vnode.constraints.affinity.is_initialized():
          for aff in vnode.constraints.affinity.values():
            aff = infra.constraints.add_affinity(
              id=aff.id.get_value(),
              value=aff.object.get_value())
            self.log.debug("Add affinity: %s to %s" % (aff, infra.id))
        # Add antiaffinity list
        if vnode.constraints.antiaffinity.is_initialized():
          for naff in vnode.constraints.antiaffinity.values():
            naff = infra.constraints.add_antiaffinity(
              id=naff.id.get_value(),
              value=naff.object.get_value())
            self.log.debug("Add antiaffinity: %s to %s" % (naff, infra.id))
        # Add variables dict
        if vnode.constraints.variable.is_initialized():
          for var in vnode.constraints.variable.values():
            var = infra.constraints.add_variable(
              key=var.id.get_value(),
              id=var.object.get_value())
            self.log.debug("Add variable: %s to %s" % (var, infra.id))
        # Add constraint list
        if vnode.constraints.constraint.is_initialized():
          for constraint in vnode.constraints.constraint.values():
            formula = infra.constraints.add_constraint(
              id=constraint.id.get_value(),
              formula=constraint.formula.get_value())
            self.log.debug("Add constraint: %s to %s" % (formula, infra.id))

      # Copy metadata
      self.log.debug("Parse Infra node metadata...")
      for key in vnode.metadata:  # Optional - node.metadata
        if key in ('bandwidth', 'delay'):
          # Internally used metadata --> already processed
          pass
        elif str(key).startswith("constraint"):
          self.log.debug("Constraint entry detected!")
          raw = vnode.metadata[key].value.get_value()
          values = json.loads(raw.replace("'", '"'))
          self.log.log(VERBOSE, "Parsed metadata:\n%s" % values)
          bandwidth = path = delay = None
          if "bandwidth" in values:
            try:
              bandwidth = float(values['bandwidth']['value'])
            except ValueError:
              self.log.warning("Bandwidth in requirement metadata: %s is not a "
                               "valid float value!" % values['bandwidth'])
            path = values['bandwidth']['path']

          if "delay" in values:
            try:
              delay = float(values['delay']['value'])
            except ValueError:
              self.log.warning("Delay in requirement metadata: %s is not a "
                               "valid float value!" % values['delay'])
            if path != values['delay']['path']:
              self.log.warning(
                "Delay/bandwidth path entry is different in E2E requirement "
                "metadata: %s!" % raw)
              continue

          src_port = dst_port = None
          if path is None:
            continue
          sg_id = int(path[0])
          for p in infra.ports:
            for f in p.flowrules:
              if f.id == sg_id:
                src_port = p
                self.log.debug("Found src port: %s" % p.id)
                break
          sg_id = int(path[-1])
          for f in infra.flowrules():
            if f.id == sg_id:
              dst_port_id = f.action.split(';')[0].split('=')[1]
              dst_port = infra.ports[dst_port_id]
              self.log.debug("Found dst port: %s" % dst_port_id)
              break

          if src_port is None or dst_port is None:
            self.log.warning(
              "Port reference is missing for Requirement link!")
            continue
          req_id = str(key).split(':')[1]
          req = nffg.add_req(id=req_id,
                             src_port=src_port,
                             dst_port=dst_port,
                             bandwidth=bandwidth,
                             delay=delay,
                             sg_path=path)
          self.log.debug("Created Requirement link: %s" % req)
        else:
          infra.add_metadata(name=key,
                             value=vnode.metadata[key].value.get_value())

  def _parse_virtualizer_links (self, nffg, virtualizer):
    """
    Parse links from Virtualizer.

    :param nffg: Container NFFG
    :type nffg: :class:`NFFG`
    :param virtualizer: Virtualizer object
    :type virtualizer: Virtualizer
    :return: None
    """
    # Store added link in a separate structure for simplicity and speed
    added_links = []
    # Add links connecting infras
    for vlink in virtualizer.links:
      try:
        src_port = vlink.src.get_target()
      except StandardError:
        self.log.exception(
          "Got unexpected exception during acquisition of link's src Port!")
      src_node = src_port.get_parent().get_parent()
      # Add domain name to the node id if unique_id is set
      src_node_id = self._gen_unique_bb_id(src_node)
      try:
        dst_port = vlink.dst.get_target()
      except StandardError:
        self.log.exception(
          "Got unexpected exception during acquisition of link's dst Port!")
      dst_node = dst_port.get_parent().get_parent()
      # Add domain name to the node id if unique_id is set
      dst_node_id = self._gen_unique_bb_id(dst_node)
      try:
        src_port_id = int(src_port.id.get_value())
      except ValueError:
        # self.log.warning("Source port id is not a valid number: %s" % e)
        src_port_id = src_port.id.get_value()
      try:
        dst_port_id = int(dst_port.id.get_value())
      except ValueError:
        # self.log.warning("Destination port id is not a valid number: %s" % e)
        dst_port_id = dst_port.id.get_value()
      params = dict()
      params['id'] = vlink.id.get_value()  # Mandatory - link.id
      if vlink.resources.is_initialized():
        params['delay'] = float(vlink.resources.delay.get_value()) \
          if vlink.resources.delay.is_initialized() else None
        params['bandwidth'] = float(vlink.resources.bandwidth.get_value()) \
          if vlink.resources.bandwidth.is_initialized() else None
        params['cost'] = vlink.resources.cost.get_value()
        params['qos'] = vlink.resources.qos.get_value()
      # Check the link is a possible backward link
      possible_backward = (
         "%s:%s-%s:%s" % (dst_node_id, dst_port_id, src_node_id, src_port_id))
      if possible_backward in added_links:
        params['backward'] = True
      # Add unidirectional link
      l1 = nffg.add_link(src_port=nffg[src_node_id].ports[src_port_id],
                         dst_port=nffg[dst_node_id].ports[dst_port_id],
                         **params)
      self.log.debug("Add static %slink: %s" % (
        "backward " if "backward" in params else "", l1))

      # Handle operation tag
      if vlink.get_operation() is not None:
        self.log.debug("Found operation tag: %s for link: %s" % (
          vlink.get_operation(), vlink.get_value()))
        l1.operation = vlink.get_operation()
      # Register the added link
      added_links.append(
        "%s:%s-%s:%s" % (src_node, src_port, dst_node, dst_port))

  @staticmethod
  def _parse_virtualizer_metadata (nffg, virtualizer):
    """
    Parse metadata from Virtualizer.

    Optionally can parse requirement links if they are stored in metadata.

    :param nffg: Container NFFG
    :type nffg: :class:`NFFG`
    :param virtualizer: Virtualizer object
    :type virtualizer: Virtualizer
    :return: None
    """
    for key in virtualizer.metadata:
      nffg.add_metadata(name=key,
                        value=virtualizer.metadata[key].value.get_value())

  def __process_variables (self, infra, variables):
    frs = []
    type = set()
    for var in variables:
      var = var.strip()
      for fr in infra.flowrules():
        if fr.delay == var:
          frs.append(fr)
          type.add("delay")
        if fr.bandwidth == var:
          frs.append(fr)
          type.add("bandwidth")
    if len(type) != 1:
      self.log.warning("Variables: %s refer to multiple type of fields: %s"
                       % (variables, type))
      return None, None
    type = type.pop()
    return frs, type

  def _parse_virtualizer_requirement (self, nffg):
    self.log.debug("Process requirement formulas...")
    reqs = {}
    for infra in nffg.infras:
      deletable_ids = []
      for i, (id, formula) in enumerate(
         infra.constraints.constraint.iteritems()):
        self.log.debug("Detected formula: %s" % formula)
        try:
          splitted = formula.split('|')
          variables = splitted[0].strip().split('+')
          value = float(splitted[-1])
        except:
          self.log.warning("Wrong formula format: %s" % formula)
          continue
        frs, type = self.__process_variables(infra=infra, variables=variables)
        if not (frs or type):
          continue
        # Recreate sg_path
        sg_path = [fr.id for fr in frs]
        self.log.debug("Recreated sg_hop list: %s" % sg_path)
        try:
          sport = NFFGToolBox.get_inport_of_flowrule(infra, frs[0].id)
          dport = NFFGToolBox.get_output_port_of_flowrule(infra, frs[-1])
        except RuntimeError as e:
          self.log.error("Referred port is missing from infra node: %s" % e)
          continue
        if (sport, dport) not in reqs:
          req_link = nffg.add_req(src_port=sport,
                                  dst_port=dport,
                                  id="req%s" % i,
                                  sg_path=sg_path)
          self.log.debug("Created requirement link: %s" % req_link)
          reqs[(sport, dport)] = req_link
        else:
          req_link = reqs[(sport, dport)]
        setattr(req_link, type, value)
        self.log.debug("Set requirement value: %s --> %s" % (type, value))
        # Remove variables from flowrules
        for fr in frs:
          setattr(fr, type, None)
        # Mark formula for deletion
        deletable_ids.append(id)
      for formula_id in deletable_ids:
        infra.constraints.del_constraint(id=formula_id)

  def _parse_sghops_from_flowrules (self, nffg):
    """
    Recreate the SG hop links based on the flowrules.
    Use the flowrule id as the is of the SG hop link.

    :param nffg: Container NFFG
    :type nffg: :class:`NFFG`
    :return: None
    """
    if not nffg.is_SBB():
      return
    self.log.debug(
      "Detected SingleBiSBiS view! Recreate SG hop links based on flowrules...")
    for sbb in nffg.infras:
      for flowrule in sbb.flowrules():
        # Get source port / in_port
        in_port = None
        flowclass = None
        fr_id = flowrule.id
        for item in flowrule.match.split(';'):
          if item.startswith('in_port'):
            in_port = item.split('=')[1]
          elif item.startswith('TAG') or item.startswith('UNTAG'):
            pass
          elif item.startswith('flowclass'):
            flowclass = item.split('=', 1)[1]
          else:
            flowclass = item
        if in_port is not None:
          # Detect the connected NF/SAP port for sg_hop
          opposite_node = [l.dst for u, v, l in nffg.real_out_edges_iter(sbb.id)
                           if l.src.id == in_port]
          if len(opposite_node) == 1:
            in_port = opposite_node.pop()
            self.log.debug("Detected src port for SG hop: %s" % in_port)
          else:
            self.log.warning(
              "src port for SG hop: %s cannot be detected! Possible ports: %s" %
              (fr_id, opposite_node))
            continue
        else:
          self.log.warning(
            "in_port for SG hop link cannot be determined from: %s. Skip SG "
            "hop recreation..." % flowrule)
          return
        # Get destination port / output
        output = None
        for item in flowrule.action.split(';'):
          if item.startswith('output'):
            output = item.split('=')[1]
        if output is not None:
          # Detect the connected NF/SAP port for sg_hop
          opposite_node = [l.dst for u, v, l in nffg.real_out_edges_iter(sbb.id)
                           if l.src.id == output]
          if len(opposite_node) == 1:
            output = opposite_node.pop()
            self.log.debug("Detected dst port for SG hop: %s" % output)
          else:
            self.log.warning(
              "dst port for SG hop: %s cannot be detected! Possible ports: %s" %
              (fr_id, opposite_node))
            continue
        else:
          self.log.warning(
            "output for SG hop link cannot be determined from: %s. Skip SG "
            "hop recreation..." % flowrule)
          return
        sg = nffg.add_sglink(id=fr_id,
                             src_port=in_port,
                             dst_port=output,
                             flowclass=flowclass,
                             delay=flowrule.delay,
                             bandwidth=flowrule.bandwidth,
                             constraints=flowrule.constraints)
        self.log.debug("Recreated SG hop: %s" % sg)

  def parse_from_Virtualizer (self, vdata, with_virt=False,
                              create_sg_hops=False):
    """
    Convert Virtualizer3-based XML str --> NFFGModel based NFFG object

    :param vdata: XML plain data or Virtualizer object
    :type: vdata: str or Virtualizer
    :param with_virt: return with the Virtualizer object too (default: False)
    :type with_virt: bool
    :param create_sg_hops: create the SG hops (default: False)
    :type create_sg_hops: bool
    :return: created NF-FG
    :rtype: :class:`NFFG`
    """
    self.log.debug(
      "START conversion: Virtualizer(ver: %s) --> NFFG(ver: %s)" % (
        V_VERSION, N_VERSION))
    # Already in Virtualizer format
    if isinstance(vdata, virt_lib.Virtualizer):
      virtualizer = vdata
    # Plain XML string
    elif isinstance(vdata, basestring):
      try:
        self.log.debug("Converting data to graph-based NFFG structure...")
        virtualizer = virt_lib.Virtualizer.parse_from_text(text=vdata)
      except Exception as e:
        self.log.error("Got ParseError during XML->Virtualizer conversion!")
        raise RuntimeError('ParseError: %s' % e.message)
    else:
      self.log.error("Not supported type for vdata: %s" % type(vdata))
      return
    # Get NFFG init params
    nffg_id = virtualizer.id.get_value()  # Mandatory - virtualizer.id
    if virtualizer.name.is_initialized():  # Optional - virtualizer.name
      nffg_name = virtualizer.name.get_value()
    else:
      nffg_name = None
    self.log.debug("Construct NFFG based on Virtualizer(id=%s, name=%s)" % (
      nffg_id, nffg_name))
    # Create NFFG
    nffg = NFFG(id=nffg_id, name=nffg_name)
    # Parse Infrastructure Nodes from Virtualizer
    self._parse_virtualizer_nodes(nffg=nffg, virtualizer=virtualizer)
    # Parse Infrastructure links from Virtualizer
    self._parse_virtualizer_links(nffg=nffg, virtualizer=virtualizer)
    # Parse Metadata and from Virtualizer
    self._parse_virtualizer_metadata(nffg=nffg, virtualizer=virtualizer)
    # Parse requirement links from Virtualizer
    self._parse_virtualizer_requirement(nffg=nffg)
    # If the received NFFG is a SingleBiSBiS, recreate the SG hop links
    # which are in compliance with flowrules in SBB node
    if create_sg_hops:
      self._parse_sghops_from_flowrules(nffg=nffg)
    else:
      self.log.debug("Skip SG hop recreation...")
    self.log.debug("END conversion: Virtualizer(ver: %s) --> NFFG(ver: %s)" % (
      V_VERSION, N_VERSION))
    return (nffg, virtualizer) if with_virt else nffg

  def _convert_nffg_infras (self, nffg, virtualizer):
    """
    Convert infras in the given :class:`NFFG` into the given Virtualizer.

    :param nffg: NFFG object
    :type nffg: :class:`NFFG`
    :param virtualizer: Virtualizer object
    :type virtualizer: Virtualizer
    :return: None
    """
    self.log.debug("Converting infras...")
    for infra in nffg.infras:
      # Check in it's needed to remove domain from the end of id
      v_node_id = self.recreate_bb_id(id=infra.id)
      v_node_name = infra.name  # optional
      v_node_type = infra.infra_type  # Mandatory
      v_node = virt_lib.Infra_node(id=v_node_id,
                                   name=v_node_name,
                                   type=v_node_type)
      # Add resources nodes/node/resources
      v_node.resources.cpu.set_value(infra.resources.cpu)
      v_node.resources.mem.set_value(infra.resources.mem)
      v_node.resources.storage.set_value(infra.resources.storage)
      v_node.resources.cost.set_value(infra.resources.cost)
      v_node.resources.zone.set_value(infra.resources.zone)

      # Migrate metadata
      for key, value in infra.metadata.iteritems():
        v_node.metadata.add(virt_lib.MetadataMetadata(key=key, value=value))

      # Add remained NFFG-related information into metadata
      if infra.resources.delay is not None:
        v_node.metadata.add(virt_lib.MetadataMetadata(
          key="delay", value=infra.resources.delay))
      if infra.resources.bandwidth is not None:
        v_node.metadata.add(virt_lib.MetadataMetadata(
          key="bandwidth", value=infra.resources.bandwidth))
      if infra.operation is not None:
        self.log.debug("Convert operation tag: %s for infra: %s" % (
          infra.operation, infra.id))
        v_node.set_operation(operation=infra.operation, recursive=False)
      self.log.debug("Converted %s" % infra)

      # Add ports to infra
      for port in infra.ports:
        # Check if the port is a dynamic port : 23412423523445 or sap1|comp|1
        # If it is a dynamic port, skip conversion
        try:
          if not int(port.id) < 65536:
            # Dynamic port connected to a VNF - skip
            continue
        except ValueError:
          # port is not a number
          if '|' in str(port.id):
            continue
        if str(port.id).startswith("EXTERNAL"):
          self.log.debug("Port: %s in infra %s is EXTERNAL. Skip adding..."
                         % (port.id, infra.id))
          continue
        v_port = virt_lib.Port(id=str(port.id))
        # If SAP property is exist: this port connected to a SAP
        if port.sap is not None:
          v_port.sap.set_value(port.sap)
        elif port.get_property('sap'):
          v_port.sap.set_value(port.get_property('sap'))
        # Set default port-type to port-abstract
        # during SAP detection the SAP<->Node port-type will be overridden
        v_port.port_type.set_value(self.TYPE_VIRTUALIZER_PORT_ABSTRACT)
        # Additional values of SAP/NF will be set later
        # Migrate port attributes
        self.__copy_port_attrs(v_port=v_port, port=port)
        # port_type: port-abstract & sap: -    -->  regular port
        # port_type: port-abstract & sap: <SAP...>    -->  was connected to
        # an inter-domain port - set this data in Virtualizer
        if port.operation is not None:
          self.log.debug("Convert operation tag: %s for port: %s" % (
            port.operation, port.id))
          v_port.set_operation(operation=port.operation, recursive=False)
        v_node.ports.add(v_port)
        self.log.debug("Added static %s" % port)

      # Add minimalistic Nodes for supported NFs based on supported list of NFFG
      for sup in infra.supported:
        v_node.capabilities.supported_NFs.add(virt_lib.Node(id=sup, type=sup))

      # Add infra to virtualizer
      if v_node_id in virtualizer.nodes.node.keys():
        self.log.warning("Virtualizer node: %s already exists in Virtualizer: "
                         "%s!" % (v_node_id, virtualizer.id.get_value()))
      else:
        virtualizer.nodes.add(v_node)

      import copy
      copy.deepcopy(virtualizer)
      # Add intra-node link based on delay_matrix
      for src, dst, delay in infra.delay_matrix:
        if src in v_node.ports.port.keys():
          v_link_src = v_node.ports[src]
        else:
          # self.log.warning("Missing port: %s from Virtualizer node: %s"
          #                  % (src, v_node_id))
          continue
        if dst in v_node.ports.port.keys():
          v_link_dst = v_node.ports[dst]
        else:
          # self.log.warning("Missing port: %s from Virtualizer node: %s"
          #                  % (dst, v_node_id))
          continue
        v_link = virt_lib.Link(id="link-%s-%s" % (v_link_src.id.get_value(),
                                                  v_link_dst.id.get_value()),
                               src=v_link_src,
                               dst=v_link_dst,
                               resources=virt_lib.Link_resource(
                                 delay=delay))
        v_node.links.add(v_link)
        self.log.debug("Added intra-BiSBiS resource link [%s --> %s] "
                       "with delay: %s" % (src, dst, delay))

  def __copy_port_attrs (self, v_port, port):
    # Set sap.name if it has not used for storing SAP.id
    if port.name is not None:
      v_port.name.set_value(port.name)
      self.log.debug("Added name: %s" % v_port.name.get_value())
    # Convert other SAP-port-specific data
    v_port.capability.set_value(port.capability)
    v_port.sap_data.technology.set_value(port.technology)
    v_port.sap_data.role.set_value(port.role)
    v_port.sap_data.resources.delay.set_value(port.delay)
    v_port.sap_data.resources.bandwidth.set_value(port.bandwidth)
    v_port.sap_data.resources.cost.set_value(port.cost)
    v_port.sap_data.resources.qos.set_value(port.qos)
    v_port.control.controller.set_value(port.controller)
    v_port.control.orchestrator.set_value(port.orchestrator)
    v_port.addresses.l2.set_value(port.l2)
    v_port.addresses.l4.set_value(port.l4)
    for l3 in port.l3:
      v_port.addresses.l3.add(virt_lib.L3_address(id=l3.id,
                                                  name=l3.name,
                                                  configure=l3.configure,
                                                  requested=l3.requested,
                                                  provided=l3.provided))
    # Migrate metadata
    for key, value in port.metadata.iteritems():
      v_port.metadata.add(virt_lib.MetadataMetadata(key=key,
                                                    value=value))
    if port.operation is not None:
      self.log.debug("Convert operation tag: %s for port: %s" % (
        port.operation, port.id))
      v_port.set_operation(operation=port.operation,
                           recursive=False)

  def __copy_vport_attrs (self, port, vport):
    if vport.name.is_initialized():
      # infra_port.add_property("name", vport.name.get_value())
      port.name = vport.name.get_value()
    self.log.debug("Added name: %s" % port.name)
    # If sap is set and port_type is port-abstract -> this port
    # connected to an inter-domain SAP before -> save this metadata
    if vport.sap.is_initialized():
      port.add_property("sap", vport.sap.get_value())
      port.sap = vport.sap.get_value()
    if vport.capability.is_initialized():
      port.capability = vport.capability.get_value()
      self.log.debug("Added capability: %s" % port.capability)
    if vport.sap_data.is_initialized():
      if vport.sap_data.technology.is_initialized():
        port.technology = vport.sap_data.technology.get_value()
        self.log.debug("Added technology: %s" % port.technology)
      if vport.sap_data.role.is_initialized():
        port.role = vport.sap_data.technology.get_value()
        self.log.debug("Added role: %s" % port.role)
      if vport.sap_data.resources.is_initialized():
        if vport.sap_data.resources.delay.is_initialized():
          port.delay = vport.sap_data.resources.delay.get_value()
          self.log.debug("Added delay: %s" % port.delay)
        if vport.sap_data.resources.bandwidth.is_initialized():
          port.bandwidth = vport.sap_data.resources.bandwidth.get_value()
          self.log.debug("Added bandwidth: %s" % port.bandwidth)
        if vport.sap_data.resources.cost.is_initialized():
          port.cost = vport.sap_data.resources.cost.get_value()
          self.log.debug("Added cost: %s" % port.cost)
        if vport.sap_data.resources.qos.is_initialized():
          port.qos = vport.sap_data.resources.qos.get_value()
          self.log.debug("Added qos: %s" % port.qos)
    if vport.control.is_initialized():
      if vport.control.controller.is_initialized():
        port.controller = vport.conntrol.controller.get_value()
        self.log.debug("Added controller: %s" % port.controller)
      if vport.control.orchestrator.is_initialized():
        port.orchestrator = vport.conntrol.orchestrator.get_value()
        self.log.debug("Added orchestrator: %s" % port.orchestrator)
    if vport.addresses.is_initialized():
      self.log.debug("Translate addresses...")
      port.l2 = vport.addresses.l2.get_value()
      port.l4 = vport.addresses.l4.get_value()
      for l3 in vport.addresses.l3.itervalues():
        port.l3.add_l3address(id=l3.id.get_value(),
                              name=l3.name.get_value(),
                              configure=l3.configure.get_value(),
                              client=l3.client.get_value(),
                              requested=l3.requested.get_value(),
                              provided=l3.provided.get_value())
    # Add metadata from non-sap port to infra port metadata
    for key in vport.metadata:
      port.add_metadata(name=key, value=vport.metadata[key].value.get_value())
    # Handle operation tag
    if vport.get_operation() is not None:
      self.log.debug("Found operation tag: %s for port: %s" % (
        vport.get_operation(), vport.id.get_value()))
      port.operation = vport.get_operation()
    pass

  def _convert_nffg_saps (self, nffg, virtualizer):
    """
    Convert SAPs in the given :class:`NFFG` into the given Virtualizer.

    :param nffg: NFFG object
    :type nffg: :class:`NFFG`
    :param virtualizer: Virtualizer object
    :type virtualizer: Virtualizer
    :return: None
    """
    self.log.debug("Converting SAPs...")
    # Rewrite SAP - Node ports to add SAP to Virtualizer
    for sap in nffg.saps:
      if str(sap.id).startswith("EXTERNAL"):
        self.log.debug("SAP: %s is an EXTERNAL dynamic SAP. Skipping..."
                       % sap.id)
        continue
      for s, n, link in nffg.network.edges_iter([sap.id], data=True):
        if link.type != NFFG.TYPE_LINK_STATIC:
          continue
        sap_port = link.src
        # Rewrite port-type to port-sap
        infra_id = self.recreate_bb_id(id=n)
        v_sap_port = virtualizer.nodes[infra_id].ports[str(link.dst.id)]
        if link.src.role == "EXTERNAL":
          self.log.debug("SAP: %s is an EXTERNAL dynamic SAP. Removing..."
                         % sap.id)
          virtualizer.nodes[infra_id].ports.remove(v_sap_port)
          continue
        v_sap_port.port_type.set_value(self.TYPE_VIRTUALIZER_PORT_SAP)

        # Check if the SAP is an inter-domain SAP
        if sap_port.sap is not None:
          # Set static 'sap' value
          v_sap_port.sap.set_value(sap_port.sap)
        elif sap_port.has_property("type") == "inter-domain":
          # If sap metadata is set by merge, use this value else the SAP.id
          if sap_port.has_property('sap'):
            v_sap_port.sap.set_value(sap_port.get_property('sap'))
          else:
            v_sap_port.sap.set_value(sap.id)
        # Check if the SAP is a bound, inter-domain SAP (no sap and port
        # property are set in this case)
        elif sap.binding is not None:
          v_sap_port.sap.set_value(s)
          self.log.debug(
            "Set port: %s in infra: %s as an inter-domain SAP with"
            " 'sap' value: %s" % (link.dst.id, n,
                                  v_sap_port.sap.get_value()))
        else:
          # If sap is not inter-domain SAP, use name field to store sap id and
          v_sap_port.name.set_value("%s:%s" % (self.SAP_NAME_PREFIX, sap.id))
        self.__copy_port_attrs(v_port=v_sap_port, port=sap_port)
        self.log.debug(
          "Converted %s to port: %s in infra: %s" % (sap, link.dst.id, n))

  def _convert_nffg_edges (self, nffg, virtualizer):
    """
    Convert edge links in the given :class:`NFFG` into the given Virtualizer.

    :param nffg: NFFG object
    :type nffg: :class:`NFFG`
    :param virtualizer: Virtualizer object
    :type virtualizer: Virtualizer
    :return: None
    """
    self.log.debug("Converting edges...")
    # Add edge-link to Virtualizer
    for link in nffg.links:
      # Skip backward and non-static link conversion <-- Virtualizer links
      # are bidirectional
      if link.type != NFFG.TYPE_LINK_STATIC:
        continue
      # SAP - Infra links are not stored in Virtualizer format
      if link.src.node.type == NFFG.TYPE_SAP or \
         link.dst.node.type == NFFG.TYPE_SAP:
        continue
      self.log.debug(
        "Added link: Node: %s, port: %s <--> Node: %s, port: %s" % (
          link.src.node.id, link.src.id, link.dst.node.id, link.dst.id))
      src_node_id = self.recreate_bb_id(id=link.src.node.id)
      dst_node_id = self.recreate_bb_id(id=link.dst.node.id)
      v_link = virt_lib.Link(
        id=link.id,
        src=virtualizer.nodes[src_node_id].ports[str(link.src.id)],
        dst=virtualizer.nodes[dst_node_id].ports[str(link.dst.id)],
        resources=virt_lib.Link_resource(delay=link.delay,
                                         bandwidth=link.bandwidth,
                                         cost=link.cost, qos=link.qos))
      # Handel operation tag
      if link.operation is not None:
        self.log.debug(
          "Convert operation tag: %s for link: %s" % (link.operation, link.id))
        v_link.set_operation(operation=link.operation, recursive=False)
      # Call bind to resolve src,dst references to workaround a bug
      # v_link.bind()
      virtualizer.links.add(v_link)

  def _convert_nffg_reqs (self, nffg, virtualizer):
    """
    Convert requirement links in the given :class:`NFFG` into given Virtualizer
    using infra node's metadata list.

    :param nffg: NFFG object
    :type nffg: :class:`NFFG`
    :param virtualizer: Virtualizer object
    :type virtualizer: Virtualizer
    :return: None
    """
    self.log.debug("Converting requirement links...")
    for req in nffg.reqs:
      self.log.debug('Converting requirement link: %s' % req)
      # Get container node
      if req.src.node.id != req.dst.node.id:
        self.log.warning("Requirement link has wrong format: src/dst port is "
                         "not connected to the same BiSBiS node!")
        continue
      infra_id = self.recreate_bb_id(id=req.src.node.id)
      self.log.debug("Detected infra node: %s for requirement link: %s" %
                     (infra_id, req))
      # Assembly delay req
      if req.delay is not None:
        self.log.debug("Creating formula for delay requirement...")
        formula = []
        for hop in req.sg_path:
          try:
            v_fe = virtualizer.nodes[infra_id].flowtable[str(hop)]
          except:
            self.log.warning("Flowrule: %s was not found in Virtualizer!" % hop)
            continue
          try:
            var_delay = v_fe.resources.delay.get_value()
          except:
            var_delay = None
          if not (var_delay and str(var_delay).startswith('$')):
            dvar = "$d" + str(v_fe.id.get_value())
            self.log.debug("Delay value: %s is not a variable! "
                           "Replacing with: %s" % (var_delay, dvar))
            v_fe.resources.delay.set_value(dvar)
            formula.append("$d" + str(v_fe.id.get_value()))
          else:
            formula.append(var_delay)
            log.debug("Registered delay variable: %s" % var_delay)
        formula = '+'.join(formula) + "|max|%s" % req.delay
        self.log.debug("Generated delay formula: %s" % formula)
        virtualizer.nodes[infra_id].constraints.constraint.add(
          virt_lib.ConstraintsConstraint(id="delay-" + str(req.id),
                                         formula=formula))
      # Assemble bandwidth req
      if req.bandwidth is not None:
        self.log.debug("Creating formula for bandwidth requirement...")
        formula = []
        for hop in req.sg_path:
          try:
            v_fe = virtualizer.nodes[infra_id].flowtable[str(hop)]
          except:
            self.log.warning("Flowrule: %s was not found in Virtualizer!" % hop)
            continue
          try:
            var_bw = v_fe.resources.bandwidth.get_value()
          except:
            var_bw = None
          if not (var_bw and str(var_bw).startswith('$')):
            bwvar = "$bw" + str(v_fe.id.get_value())
            self.log.debug("Bandwidth value: %s is not a variable! "
                           "Replacing with: %s" % (var_bw, bwvar))
            v_fe.resources.bandwidth.set_value(bwvar)
            formula.append("$bw" + str(v_fe.id.get_value()))
          else:
            formula.append(var_bw)
            self.log.debug("Registered bandwidth variable: %s" % var_bw)
        formula = '+'.join(formula) + "||%s" % req.bandwidth
        self.log.debug("Generated bandwidth formula: %s" % formula)
        virtualizer.nodes[infra_id].constraints.constraint.add(
          virt_lib.ConstraintsConstraint(id="bandwidth-" + str(req.id),
                                         formula=formula))

  def __assemble_virt_nf (self, nf):
    v_nf_id = self.recreate_nf_id(nf.id)
    # Create Node object for NF
    v_nf = virt_lib.Node(id=v_nf_id,
                         name=nf.name,
                         type=nf.functional_type,
                         status=nf.status,
                         resources=virt_lib.Software_resource(
                           cpu=nf.resources.cpu,
                           mem=nf.resources.mem,
                           storage=nf.resources.storage,
                           cost=nf.resources.cost,
                           zone=nf.resources.zone))
    # Set deployment type, delay, bandwidth as a metadata
    if nf.deployment_type is not None:
      v_nf.metadata.add(
        virt_lib.MetadataMetadata(key='deployment_type',
                                  value=nf.deployment_type))
    if nf.resources.delay is not None:
      v_nf.metadata.add(
        virt_lib.MetadataMetadata(key='delay',
                                  value=nf.resources.delay))
    if nf.resources.bandwidth is not None:
      v_nf.metadata.add(
        virt_lib.MetadataMetadata(key='bandwidth',
                                  value=nf.resources.bandwidth))
    # Migrate metadata
    for key, value in nf.metadata.iteritems():
      if key not in ('deployment_type', 'delay', 'bandwidth'):
        v_nf.metadata.add(
          virt_lib.MetadataMetadata(key=key, value=value))

    # Handle operation tag
    if nf.operation is not None:
      self.log.debug("Convert operation tag: %s for NF: %s" %
                     (nf.operation, nf.id))
      v_nf.set_operation(operation=nf.operation, recursive=False)
    return v_nf

  def __assemble_virt_nf_port (self, port):
    v_nf_port = virt_lib.Port(id=str(port.id),
                              port_type=self.TYPE_VIRTUALIZER_PORT_ABSTRACT)
    # Convert other SAP-specific data
    v_nf_port.name.set_value(port.name)
    if 'port-type' in port.properties:
      self.log.warning("Unexpected inter-domain port in NF: %s" % port)
    if 'sap' in port.properties:
      v_nf_port.sap.set_value(port.properties['sap'])
      v_nf_port.port_type.set_value(self.TYPE_VIRTUALIZER_PORT_SAP)
    elif port.sap is not None:
      v_nf_port.sap.set_value(port.sap)
      v_nf_port.port_type.set_value(self.TYPE_VIRTUALIZER_PORT_SAP)
    if port.capability:
      self.log.debug("Translate capability...")
    v_nf_port.capability.set_value(port.capability)
    if any((port.technology, port.role, port.delay, port.bandwidth,
            port.cost)):
      self.log.debug("Translate sap_data...")
    v_nf_port.sap_data.technology.set_value(port.technology)
    v_nf_port.sap_data.role.set_value(port.role)
    v_nf_port.sap_data.resources.delay.set_value(port.delay)
    v_nf_port.sap_data.resources.bandwidth.set_value(
      port.bandwidth)
    v_nf_port.sap_data.resources.cost.set_value(port.cost)
    v_nf_port.sap_data.resources.qos.set_value(port.qos)
    if any((port.controller, port.orchestrator)):
      self.log.debug("Translate controller...")
    v_nf_port.control.controller.set_value(port.controller)
    v_nf_port.control.orchestrator.set_value(port.orchestrator)
    if any((port.l2, port.l4, len(port.l3))):
      self.log.debug("Translate addresses...")
    v_nf_port.addresses.l2.set_value(port.l2)
    v_nf_port.addresses.l4.set_value(port.l4)
    for l3 in port.l3:
      v_nf_port.addresses.l3.add(
        virt_lib.L3_address(id=l3.id,
                            name=l3.name,
                            configure=l3.configure,
                            requested=l3.requested,
                            provided=l3.provided))
    # Migrate metadata
    if len(port.metadata):
      self.log.debug("Translate metadata...")
    for property, value in port.metadata.iteritems():
      v_nf_port.metadata.add(virt_lib.MetadataMetadata(key=property,
                                                       value=value))
    # Handle operation tag
    if port.operation is not None:
      self.log.debug("Convert operation tag: %s for port: %s" % (
        port.operation, port.id))
      v_nf_port.set_operation(operation=port.operation,
                              recursive=False)
    return v_nf_port

  def _convert_nffg_nfs (self, virtualizer, nffg):
    """
    Convert NFs in the given :class:`NFFG` into the given Virtualizer.

    :param virtualizer: Virtualizer object based on ETH's XML/Yang version.
    :param nffg: splitted NFFG (not necessarily in valid syntax)
    :return: modified Virtualizer object
    :rtype: :class:`Virtualizer`
    """
    self.log.debug("Converting NFs...")
    # Check every infra Node
    for infra in nffg.infras:
      # Cache discovered NF to avoid multiple detection of NF which has more
      # than one port
      discovered_nfs = []
      # Recreate the original Node id
      v_node_id = self.recreate_bb_id(id=infra.id)
      # Check in Infra exists in the Virtualizer
      if v_node_id not in virtualizer.nodes.node.keys():
        self.log.warning(
          "InfraNode: %s is not in the Virtualizer(nodes: %s)! Skip related "
          "initiations..." % (infra, virtualizer.nodes.node.keys()))
        continue
      # Get Infra node from Virtualizer
      v_node = virtualizer.nodes[v_node_id]
      # Check every outgoing edge and observe only the NF neighbours
      for nf in nffg.running_nfs(infra.id):
        v_nf_id = self.recreate_nf_id(nf.id)
        # Skip already detected NFs
        if v_nf_id in discovered_nfs:
          continue
        # Check if the NF is exist in the InfraNode
        if v_nf_id not in v_node.NF_instances.node.keys():
          self.log.debug("Found uninitiated NF: %s in mapped NFFG" % nf)
          # Create Node object for NF
          v_nf = self.__assemble_virt_nf(nf=nf)
          # Add NF to Infra object
          v_node.NF_instances.add(v_nf)
          # Cache discovered NF
          discovered_nfs.append(v_nf_id)
          self.log.debug(
            "Added NF: %s to Infra node(id=%s, name=%s, type=%s)" % (
              nf, v_node.id.get_as_text(),
              v_node.name.get_as_text(),
              v_node.type.get_as_text()))
          # Add NF ports
          for port in nf.ports:
            v_nf_port = self.__assemble_virt_nf_port(port=port)
            v_node.NF_instances[v_nf.id.get_value()].ports.add(v_nf_port)
            self.log.debug("Added Port: %s to NF node: %s" %
                           (port, v_nf.id.get_as_text()))
        else:
          self.log.debug("%s already exists in the Virtualizer(id=%s, "
                         "name=%s)" % (nf, virtualizer.id.get_as_text(),
                                       virtualizer.name.get_as_text()))

  # noinspection PyDefaultArgument
  def _convert_nffg_flowrules (self, virtualizer, nffg):
    """
    Convert flowrules in the given :class:`NFFG` into the given Virtualizer.

    :param virtualizer: Virtualizer object based on ETH's XML/Yang version.
    :param nffg: splitted NFFG (not necessarily in valid syntax)
    :return: modified Virtualizer object
    :rtype: :class:`Virtualizer`
    """
    self.log.debug("Converting flowrules...")
    # Check every infra Node
    for infra in nffg.infras:
      # Recreate the original Node id
      v_node_id = self.recreate_bb_id(id=infra.id)
      # Check in Infra exists in the Virtualizer
      if v_node_id not in virtualizer.nodes.node.keys():
        self.log.warning(
          "InfraNode: %s is not in the Virtualizer(nodes: %s)! Skip related "
          "initiations..." % (infra, virtualizer.nodes.node.keys()))
        continue
      # Get Infra node from Virtualizer
      v_node = virtualizer.nodes[v_node_id]
      # traverse every port in the Infra node
      for port in infra.ports:
        # Check every flowrule
        for fr in port.flowrules:
          self.log.debug("Converting flowrule: %s..." % fr)
          # Mandatory id
          fe_id = fr.id
          # Define constant priority
          # fe_pri = str(100)
          fe_pri = None

          # Check if match starts with in_port
          fe = fr.match.split(';')
          if fe[0].split('=')[0] != "in_port":
            self.log.warning("Missing 'in_port' from match in %s. Skip "
                             "flowrule conversion..." % fr)
            continue
          # Check if the src port is a physical or virtual port
          in_port = fe[0].split('=')[1]
          if in_port in v_node.ports.port.keys():
            # Flowrule in_port is a phy port in Infra Node
            in_port = v_node.ports[in_port]
            self.log.debug("Identify in_port: %s in match as a physical port "
                           "in the Virtualizer" % in_port.id.get_as_text())
          else:
            ext_sap = [l.dst for u, v, l in
                       nffg.network.out_edges_iter([infra.id], data=True)
                       if l.dst.node.type == "SAP" and
                       str(l.src.id) == in_port and l.dst.role == "EXTERNAL"]
            if len(ext_sap) > 0:
              self.log.debug("Identify in_port: %s in match as an EXTERNAL "
                             "port." % in_port)
              in_port = ext_sap[0].get_property("path")
            else:
              self.log.debug("Identify in_port: %s in match as a dynamic port. "
                             "Tracking associated NF port in the "
                             "Virtualizer..." % in_port)
              # in_port is a dynamic port --> search for connected NF's port
              v_nf_port = [l.dst for u, v, l in
                           nffg.network.out_edges_iter([infra.id], data=True)
                           if l.type == NFFG.TYPE_LINK_DYNAMIC and
                           str(l.src.id) == in_port]
              # There should be only one link between infra and NF
              if len(v_nf_port) < 1:
                self.log.warning("NF port is not found for dynamic Infra port: "
                                 "%s defined in match field! Skip flowrule "
                                 "conversion..." % in_port)
                continue
              v_nf_port = v_nf_port[0]
              v_nf_id = self.recreate_nf_id(v_nf_port.node.id)
              in_port = v_node.NF_instances[v_nf_id].ports[str(v_nf_port.id)]
              self.log.debug("Found associated NF port: node=%s, port=%s" % (
                in_port.get_parent().get_parent().id.get_as_text(),
                in_port.id.get_as_text()))
          # Process match field
          match = self._convert_flowrule_match(fr.match)
          # Check if action starts with outport
          fe = fr.action.split(';')
          if fe[0].split('=')[0] != "output":
            self.log.warning("Missing 'output' from action in %s."
                             "Skip flowrule conversion..." % fr)
            continue
          # Check if the dst port is a physical or virtual port
          out_port = fe[0].split('=')[1]
          if out_port in v_node.ports.port.keys():
            # Flowrule output is a phy port in Infra Node
            out_port = v_node.ports[out_port]
            self.log.debug("Identify outport: %s in action as a physical port "
                           "in the Virtualizer" % out_port.id.get_as_text())
          else:
            ext_sap = [l.dst for u, v, l in
                       nffg.network.out_edges_iter([infra.id], data=True)
                       if l.dst.node.type == "SAP" and
                       str(l.src.id) == out_port and l.dst.role == "EXTERNAL"]
            if len(ext_sap) > 0:
              self.log.debug("Identify out_port: %s in action as an EXTERNAL "
                             "port." % out_port)
              out_port = ext_sap[0].get_property("path")
            else:
              self.log.debug(
                "Identify outport: %s in action as a dynamic port. "
                "Track associated NF port in the Virtualizer..." %
                out_port)
              # out_port is a dynamic port --> search for connected NF's port
              v_nf_port = [l.dst for u, v, l in
                           nffg.network.out_edges_iter([infra.id], data=True)
                           if l.type == NFFG.TYPE_LINK_DYNAMIC and
                           str(l.src.id) == out_port]
              if len(v_nf_port) < 1:
                self.log.warning("NF port is not found for dynamic Infra port: "
                                 "%s defined in action field! Skip flowrule "
                                 "conversion..." % out_port)
                continue
              v_nf_port = v_nf_port[0]
              v_nf_id = self.recreate_nf_id(v_nf_port.node.id)
              out_port = v_node.NF_instances[v_nf_id].ports[str(v_nf_port.id)]
              self.log.debug("Found associated NF port: node=%s, port=%s" % (
                out_port.get_parent().get_parent().id.get_as_text(),
                out_port.id.get_as_text()))
          # Process action field
          action = self._convert_flowrule_action(fr.action)
          # Process resource fields
          _resources = virt_lib.Link_resource(delay=fr.delay,
                                              bandwidth=fr.bandwidth,
                                              cost=fr.cost, qos=fr.qos)
          # Flowrule name is not used
          v_fe_name = None
          # Add Flowentry with converted params
          virt_fe = virt_lib.Flowentry(id=fe_id, priority=fe_pri, port=in_port,
                                       match=match, action=action, out=out_port,
                                       resources=_resources, name=v_fe_name)
          self.log.log(VERBOSE, "Generated Flowentry:\n%s" %
                       v_node.flowtable.add(virt_fe).xml())
          # Handel operation tag
          if fr.operation is not None:
            self.log.debug("Convert operation tag: %s for flowrule: %s" % (
              fr.operation, fr.id))
            virt_fe.set_operation(operation=str(fr.operation), recursive=False)

  def _get_vnode_by_id (self, virtualizer, id):
    for vnode in virtualizer.nodes:
      bb_node_id = self.recreate_bb_id(id)
      if vnode.id.get_as_text() == bb_node_id:
        return vnode
      for vnf in vnode.NF_instances:
        vnf_id = self.recreate_nf_id(id)
        if vnf.id.get_value() == vnf_id:
          return vnf

  def __set_vnode_constraints (self, vnode, infra, virtualizer):
    # Add affinity
    for id, aff in infra.constraints.affinity.iteritems():
      v_aff_node = self._get_vnode_by_id(virtualizer=virtualizer, id=aff)
      if v_aff_node is None:
        self.log.warning("Referenced Node: %s is not found for affinity!"
                         % aff)
        continue
      self.log.debug(
        "Found reference for affinity: %s in Infra: %s" % (aff, infra.id))
      vnode.constraints.affinity.add(
        virt_lib.ConstraintsAffinity(id=str(id),
                                     object=v_aff_node.get_path()))
    # Add antiaffinity
    for id, naff in infra.constraints.antiaffinity.iteritems():
      v_naff_node = self._get_vnode_by_id(virtualizer=virtualizer, id=naff)
      if v_naff_node is None:
        self.log.warning("Referenced Node: %s is not found for anti-affinity!"
                         % naff)
        continue
      self.log.debug(
        "Found reference for antiaffinity: %s in Infra: %s" % (
          naff, infra.id))
      vnode.constraints.antiaffinity.add(
        virt_lib.ConstraintsAntiaffinity(id=str(id),
                                         object=v_naff_node.get_path()))
    # Add variable
    for key, value in infra.constraints.variable.iteritems():
      v_var_node = self._get_vnode_by_id(virtualizer=virtualizer, id=value)
      if v_var_node is None:
        self.log.warning("Referenced Node: %s is not found for variable: "
                         "%s!" % (value, key))
        continue
      self.log.debug(
        "Found reference for variable: %s in Infra: %s" % (key, infra.id))
      vnode.constraints.constraint.add(
        virt_lib.ConstraintsVariable(id=str(key),
                                     object=v_var_node.get_path()))
    # Add constraint
    for id, cons in infra.constraints.constraint.iteritems():
      self.log.debug("Add formula: %s to Infra: %s" % (cons, infra.id))
      vnode.constraints.constraint.add(
        virt_lib.ConstraintsConstraint(id=str(id),
                                       formula=cons))
    # Add restorability
    if infra.constraints.restorability is not None:
      self.log.debug("Add restorability: %s to Infra: %s"
                     % (infra.constraints.restorability, infra.id))
      vnode.constraints.restorability.set_value(infra.constraints.restorability)

  def __set_vnf_constraints (self, vnode, nf, virtualizer):
    v_nf_id = self.recreate_nf_id(nf.id)
    vnf = vnode.NF_instances[v_nf_id]
    # Add affinity
    for id, aff in nf.constraints.affinity.iteritems():
      v_aff_node = self._get_vnode_by_id(virtualizer=virtualizer, id=aff)
      if v_aff_node is None:
        self.log.warning("Referenced Node: %s is not found for affinity!"
                         % aff)
        continue
      self.log.debug(
        "Found reference for affinity: %s in NF: %s" % (aff, nf.id))
      vnf.constraints.affinity.add(
        virt_lib.ConstraintsAffinity(id=str(id),
                                     object=v_aff_node.get_path()))
    # Add antiaffinity
    for id, naff in nf.constraints.antiaffinity.iteritems():
      v_naff_node = self._get_vnode_by_id(virtualizer=virtualizer, id=naff)
      if v_naff_node is None:
        self.log.warning(
          "Referenced Node: %s is not found for anti-affinity!"
          % naff)
        continue
      self.log.debug(
        "Found reference for antiaffinity: %s in NF: %s" % (naff, nf.id))
      vnf.constraints.antiaffinity.add(
        virt_lib.ConstraintsAntiaffinity(id=str(id),
                                         object=v_naff_node.get_path()))
    # Add variable
    for key, value in nf.constraints.variable.iteritems():
      v_var_node = self._get_vnode_by_id(virtualizer=virtualizer, id=value)
      if v_var_node is None:
        self.log.warning("Referenced Node: %s is not found for variable: "
                         "%s!" % (value, key))
        continue
      self.log.debug(
        "Found reference for variable: %s in NF: %s" % (key, nf.id))
      vnf.constraints.constraint.add(
        virt_lib.ConstraintsVariable(id=str(key),
                                     object=v_var_node.get_path()))
    # Add constraint
    for id, cons in nf.constraints.constraint.iteritems():
      self.log.debug("Add formula: %s to NF: %s" % (cons, nf.id))
      vnf.constraints.constraint.add(
        virt_lib.ConstraintsConstraint(id=str(id),
                                       formula=cons))
    # Add restorability
    if nf.constraints.restorability is not None:
      self.log.debug("Add restorability: %s to NF: %s"
                     % (nf.constraints.restorability, nf.id))
      vnf.constraints.restorability.set_value(nf.constraints.restorability)

  def __set_flowentry_constraints (self, vnode, flowrule, virtualizer):
    v_fe = vnode.flowtable[str(flowrule.id)]
    # Add affinity
    for id, aff in flowrule.constraints.affinity.iteritems():
      v_aff_node = self._get_vnode_by_id(virtualizer=virtualizer, id=aff)
      if v_aff_node is None:
        self.log.warning("Referenced Node: %s is not found for affinity!" % aff)
        continue
      self.log.debug("Found reference for affinity: %s in Flowrule: %s"
                     % (aff, flowrule.id))
      v_fe.constraints.affinity.add(
        virt_lib.ConstraintsAffinity(id=str(id),
                                     object=v_aff_node.get_path()))
    # Add antiaffinity
    for id, naff in flowrule.constraints.antiaffinity.iteritems():
      v_naff_node = self._get_vnode_by_id(virtualizer=virtualizer, id=naff)
      if v_naff_node is None:
        self.log.warning("Referenced Node: %s is not found for anti-affinity!"
                         % naff)
        continue
      self.log.debug("Found reference for antiaffinity: %s in Flowrule: %s"
                     % (naff, flowrule.id))
      v_fe.constraints.antiaffinity.add(
        virt_lib.ConstraintsAntiaffinity(id=str(id),
                                         object=v_naff_node.get_path()))
    # Add variable
    for key, value in flowrule.constraints.variable.iteritems():
      v_var_node = self._get_vnode_by_id(virtualizer=virtualizer, id=value)
      if v_var_node is None:
        self.log.warning("Referenced Node: %s is not found for variable: %s!"
                         % (value, key))
        continue
      self.log.debug("Found reference for variable: %s in Flowrule: %s"
                     % (key, flowrule.id))
      v_fe.constraints.constraint.add(
        virt_lib.ConstraintsVariable(id=str(key),
                                     object=v_var_node.get_path()))
    # Add constraint
    for id, cons in flowrule.constraints.constraint.iteritems():
      self.log.debug("Add constraint: %s:%s to Flowrule: %s"
                     % (id, cons, flowrule.id))
      v_fe.constraints.constraint.add(
        virt_lib.ConstraintsConstraint(id=str(id),
                                       formula=cons))
    # Add restorability
    if flowrule.constraints.restorability is not None:
      self.log.debug("Add restorability: %s to Flowrule: %s"
                     % (flowrule.constraints.restorability, flowrule.id))
      v_fe.constraints.restorability.set_value(
        flowrule.constraints.restorability)

  def _convert_nffg_constraints (self, virtualizer, nffg):
    self.log.debug("Convert constraints...")
    for infra in nffg.infras:
      # Recreate the original Node id
      v_node_id = self.recreate_bb_id(id=infra.id)
      # Check if Infra exists in the Virtualizer
      if v_node_id not in virtualizer.nodes.node.keys():
        self.log.warning(
          "InfraNode: %s is not in the Virtualizer(nodes: %s)! Skip related "
          "initiations..." % (infra, virtualizer.nodes.node.keys()))
        continue
      # Get Infra node from Virtualizer
      vnode = virtualizer.nodes[v_node_id]
      self.__set_vnode_constraints(vnode=vnode,
                                   infra=infra,
                                   virtualizer=virtualizer)
      # Check connected NF constraints
      for nf in nffg.running_nfs(infra.id):
        self.__set_vnf_constraints(vnode=vnode,
                                   nf=nf,
                                   virtualizer=virtualizer)
      for flowrule in infra.flowrules():
        self.__set_flowentry_constraints(vnode=vnode,
                                         flowrule=flowrule,
                                         virtualizer=virtualizer)

  def dump_to_Virtualizer (self, nffg):
    """
    Convert given :class:`NFFG` to Virtualizer format.

    :param nffg: topology description
    :type nffg: :class:`NFFG`
    :return: topology in Virtualizer format
    :rtype: Virtualizer
    """
    self.log.debug(
      "START conversion: NFFG(ver: %s) --> Virtualizer(ver: %s)" % (
        N_VERSION, V_VERSION))

    self.log.debug("Converting data to XML-based Virtualizer structure...")
    # Create Virtualizer with default id,name
    v_id = str(nffg.id)
    v_name = str(nffg.name) if nffg.name else None
    virtualizer = virt_lib.Virtualizer(id=v_id, name=v_name)
    self.log.debug("Creating Virtualizer based on %s" % nffg)
    # Convert NFFG metadata
    for key, value in nffg.metadata.iteritems():
      meta_key = str(key)
      meta_value = str(value) if value is not None else None
      virtualizer.metadata.add(item=virt_lib.MetadataMetadata(key=meta_key,
                                                              value=meta_value))
    # Convert Infras
    self._convert_nffg_infras(nffg=nffg, virtualizer=virtualizer)
    # Convert SAPs
    self._convert_nffg_saps(nffg=nffg, virtualizer=virtualizer)
    # Convert edge links
    self._convert_nffg_edges(nffg=nffg, virtualizer=virtualizer)
    # Convert NFs
    self._convert_nffg_nfs(nffg=nffg, virtualizer=virtualizer)
    # Convert Flowrules
    self._convert_nffg_flowrules(nffg=nffg, virtualizer=virtualizer)
    # Convert requirement links as metadata
    self._convert_nffg_reqs(nffg=nffg, virtualizer=virtualizer)
    # Convert constraints
    self._convert_nffg_constraints(nffg=nffg, virtualizer=virtualizer)
    # explicitly call bind to resolve relative paths for safety reason
    virtualizer.bind(relative=True)
    self.log.debug(
      "END conversion: NFFG(ver: %s) --> Virtualizer(ver: %s)" % (
        N_VERSION, V_VERSION))
    # Return with created Virtualizer
    return virtualizer

  @staticmethod
  def clear_installed_elements (virtualizer):
    """
    Remove NFs and flowrules from given Virtualizer.

    :param virtualizer: Virtualizer object need to clear
    :type virtualizer: Virtualizer
    :return: cleared original virtualizer
    :rtype: Virtualizer
    """
    for vnode in virtualizer.nodes:
      vnode.NF_instances.node.clear_data()
      vnode.flowtable.flowentry.clear_data()
    # explicitly call bind to resolve absolute paths for safety reason
    # virtualizer.bind(relative=True)
    return virtualizer

  def adapt_mapping_into_Virtualizer (self, virtualizer, nffg, reinstall=False):
    """
    Install the mapping related modification into a Virtualizer and return
    with the new Virtualizer object.

    :param virtualizer: Virtualizer object based on ETH's XML/Yang version.
    :param nffg: splitted NFFG (not necessarily in valid syntax)
    :param reinstall: need to clear every NF/flowrules from given virtualizer
    :type reinstall: bool
    :return: modified Virtualizer object
    :rtype: :class:`Virtualizer`
    """
    virt = virtualizer.full_copy()
    # Remove previously installed NFs and flowrules from Virtualizer for
    # e.g. correct diff calculation
    if reinstall:
      self.log.debug("Remove pre-installed NFs/flowrules...")
      self.clear_installed_elements(virtualizer=virt)
    self.log.debug(
      "START adapting modifications from %s into Virtualizer(id=%s, name=%s)"
      % (nffg, virt.id.get_as_text(), virt.name.get_as_text()))
    self._convert_nffg_nfs(virtualizer=virt, nffg=nffg)
    self._convert_nffg_flowrules(virtualizer=virt, nffg=nffg)
    self._convert_nffg_reqs(virtualizer=virt, nffg=nffg)
    self._convert_nffg_constraints(virtualizer=virt, nffg=nffg)
    # explicitly call bind to resolve absolute paths for safety reason
    virt.bind(relative=True)
    # virt.bind(relative=True)
    self.log.debug(
      "END adapting modifications from %s into Virtualizer(id=%s, name=%s)" % (
        nffg, virt.id.get_as_text(), virt.name.get_as_text()))
    # Return with modified Virtualizer
    return virt

  @staticmethod
  def unescape_output_hack (data):
    return data.replace("&lt;", "<").replace("&gt;", ">")

  def _generate_sbb_base (self, request):
    """
    Generate a SingleBiSBiS node for service request conversion utilize the
    topology specific data and SAPs from the given `request`.

    :param request: utilized service request
    :type request: :class:`NFFG`
    :return: generated SBB
    :rtype: :class:`Virtualizer`
    """
    # Generate base SBB node
    self.log.debug("Add main Virtualizer...")
    base = Virtualizer(id="SingleBiSBiS", name="Single-BiSBiS-View")
    self.log.debug("Add SBB node...")
    sbb = base.nodes.add(item=virt_lib.Infra_node(id="SingleBiSBiS",
                                                  name="SingleBiSBiS",
                                                  type="BiSBiS"))
    sbb.metadata.add(virt_lib.MetadataMetadata(key="generated", value=True))
    self.log.debug("Add SAPs from request...")
    # Add topology specific SAPs from request
    for sap in request.saps:
      v_sap_port = sbb.ports.add(
        virt_lib.Port(id=sap.id,
                      name=sap.name,
                      port_type=self.TYPE_VIRTUALIZER_PORT_SAP))
      if len(sap.ports) > 1:
        self.log.warning("Multiple SAP port detected!")
      sap_port = sap.ports.container[0]
      self.__copy_port_attrs(v_port=v_sap_port, port=sap_port)
      self.log.debug("Added SAP port: %s" % v_sap_port.id.get_value())
    return base

  def convert_service_request_init (self, request, base=None, reinstall=False):
    """
    Convert service requests (given in NFFG format) into Virtualizer format
    using the given `base` Virtualizer.

    :param request: service request
    :type request: :class:`NFFG`
    :param base: base Virtualizer
    :type base: :class:`Virtualizer`
    :param reinstall: need to clear every NF/flowrules from given virtualizer
    :type reinstall: bool
    :return: converted service request
    :rtype: :class:`Virtualizer`
    """
    if base is not None:
      self.log.debug("Using given base Virtualizer: %s" % base.id.get_value())
      base = base.full_copy()
      # Remove previously installed NFs and flowrules from Virtualizer for
      # e.g. correct diff calculation
      if reinstall:
        self.log.debug("Remove pre-installed NFs/flowrules...")
        self.clear_installed_elements(virtualizer=base)
    else:
      self.log.debug("No base Virtualizer is given! Generating SingleBiSBiS...")
      base = self._generate_sbb_base(request=request)
    self.log.debug("Transfer service request ID...")
    base.id.set_value(request.id)
    base.name.set_value(request.name)
    if base.nodes.node.length() < 1:
      self.log.warning("No BiSBiS node was detected!")
      return base
    elif base.nodes.node.length() > 1:
      self.log.warning(
        "Multiple BiSBiS nodes were detected in the Virtualizer!")
    sbb = base.nodes.node[base.nodes.node.keys().pop()]
    self.log.debug("Detected SBB node: %s" % sbb.id.get_value())
    # Add NFs
    self.log.debug("Converting NFs...")
    for nf in request.nfs:
      if str(nf.id) in sbb.NF_instances.node.keys():
        self.log.error("%s already exists in the Virtualizer!" % nf.id)
        continue
      # Create Node object for NF
      v_nf = self.__assemble_virt_nf(nf=nf)
      # Add NF to Infra object
      sbb.NF_instances.add(v_nf)
      self.log.debug("Added NF: %s to Infra node(id=%s)"
                     % (nf.id, sbb.id.get_as_text()))
      # Add NF ports
      for port in nf.ports:
        v_nf_port = self.__assemble_virt_nf_port(port=port)
        sbb.NF_instances[str(nf.id)].ports.add(v_nf_port)
        self.log.debug("Added Port: %s to NF node: %s" %
                       (port, v_nf.id.get_as_text()))
      self.log.log(VERBOSE, "Created NF:\n%s" % v_nf.xml())
    # Add flowrules
    self.log.debug("Converting SG hops into flowrules...")
    for hop in request.sg_hops:
      # Get src port
      if isinstance(hop.src.node, NodeSAP):
        v_src = sbb.ports[str(hop.src.node.id)]
      else:
        v_src = sbb.NF_instances[str(hop.src.node.id)].ports[str(hop.src.id)]
      # Get dst port
      if isinstance(hop.dst.node, NodeSAP):
        v_dst = sbb.ports[str(hop.dst.node.id)]
      else:
        v_dst = sbb.NF_instances[str(hop.dst.node.id)].ports[str(hop.dst.id)]
      fe = sbb.flowtable.add(item=virt_lib.Flowentry(id=hop.id,
                                                     priority=100,
                                                     port=v_src,
                                                     out=v_dst,
                                                     match=hop.flowclass))
      fe.resources.delay.set_value(hop.delay)
      fe.resources.bandwidth.set_value(hop.bandwidth)
      self.log.debug("Added flowrule: %s" % fe.id.get_value())
      self.log.log(VERBOSE, "Created Flowrule:\n%s" % fe.xml())
    # Add requirements
    self._convert_nffg_reqs(nffg=request, virtualizer=base)
    # Check connected NF constraints
    self.log.debug("Converting constraints...")
    for nf in request.nfs:
      self.__set_vnf_constraints(vnode=sbb,
                                 nf=nf,
                                 virtualizer=base)
    # Convert NFFG metadata
    for key, value in request.metadata.iteritems():
      meta_key = str(key)
      meta_value = str(value) if value is not None else None
      base.metadata.add(item=virt_lib.MetadataMetadata(key=meta_key,
                                                       value=meta_value))
    base.bind(relative=True)
    return base

  def convert_service_request_del (self, request, base):
    """
    Delete given service request from given virtualizer.

    :param request: service request
    :type request: :class:`NFFG`
    :param base: base Virtualizer
    :type base: :class:`Virtualizer`
    :return: generated delete request
    :rtype: :class:`Virtualizer`
    """
    self.log.debug("Using given base Virtualizer: %s" % base.id.get_value())
    base = base.full_copy()
    self.log.debug("Transfer service request ID...")
    base.id.set_value(request.id)
    base.name.set_value(request.name)
    if base.nodes.node.length() > 1:
      self.log.warning("Multiple BiSBiS node detected in the Virtualizer!")
    sbb = base.nodes.node[base.nodes.node.keys().pop()]
    self.log.debug("Detected SBB node: %s" % sbb.id.get_value())
    # Add NFs
    self.log.debug("Removing NFs...")
    for nf in request.nfs:
      if str(nf.id) not in sbb.NF_instances.node.keys():
        self.log.error("NF: %s is missing from Virtualizer!" % nf.id)
        continue
      deleted = sbb.NF_instances.remove(nf.id)
      self.log.debug("Removed NF: %s" % deleted.id.get_value())
    # Add flowrules
    self.log.debug("Removing flowrules...")
    for hop in request.sg_hops:
      if str(hop.id) not in sbb.flowtable.flowentry.keys():
        self.log.error("Flowrule: %s is missing from Virtualizer!" % hop.id)
        continue
      deleted = sbb.flowtable.remove(str(hop.id))
      self.log.debug("Removed flowrule: %s" % deleted.id.get_value())
    return base


def unicode_to_str (raw):
  """
  Converter function to avoid unicode.

  :param raw: raw data from
  :return: converted data
  """
  if isinstance(raw, dict):
    return {unicode_to_str(key): unicode_to_str(value) for key, value in
            raw.iteritems()}
  elif isinstance(raw, list):
    return [unicode_to_str(element) for element in raw]
  elif isinstance(raw, unicode):
    return raw.encode('utf-8').replace(' ', '_')
  else:
    return raw
