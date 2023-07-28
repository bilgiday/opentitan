# Copyright lowRISC contributors.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0
import logging as log
from collections import OrderedDict
from functools import partial

from reggen.validate import check_bool, check_int, val_types

from .item import Node, NodeType
from .lib import simplify_addr
from .xbar import Xbar

# val_types = {
#     'd': ["int", "integer (binary 0b, octal 0o, decimal, hex 0x)"],
#     'x': ["xint", "x for undefined otherwise int"],
#     'b': [
#         "bitrange", "bit number as decimal integer, \
#                     or bit-range as decimal integers msb:lsb"
#     ],
#     'l': ["list", "comma separated list enclosed in `[]`"],
#     'ln': ["name list", 'comma separated list enclosed in `[]` of '\
#            'one or more groups that have just name and dscr keys.'\
#            ' e.g. `{ name: "name", desc: "description"}`'],
#     'lnw': ["name list+", 'name list that optionally contains a width'],
#     'lp': ["parameter list", 'parameter list having default value optionally'],
#     'g': ["group", "comma separated group of key:value enclosed in `{}`"],
#     'lg': ["list of group", "comma separated group of key:value enclosed in `{}`"\
#            " the second entry of the list is the sub group format"],
#     's': ["string", "string, typically short"],
#     't': ["text", "string, may be multi-line enclosed in `'''` "\
#           "may use `**bold**`, `*italic*` or `!!Reg` markup"],
#     'T': ["tuple", "tuple enclosed in ()"],
#     'pi': ["python int", "Native Python type int (generated)"],
#     'pb': ["python Bool", "Native Python type Bool (generated)"],
#     'pl': ["python list", "Native Python type list (generated)"],
#     'pe': ["python enum", "Native Python type enum (generated)"]
# }
addr = {
    'name': 'Address configuration',
    'description':
    '''Device Node address configuration. It contains the base address and the size in bytes.
''',
    'required': {
        'base_addr':
        ['d', 'Base address of the device. It is required for the device'],
        'size_byte':
        ['d', 'Memory space of the device. It is required for the device'],
    },
    'optional': {},
    'added': {}
}

node = {
    'name': 'Node configuration',
    'description': '''
Crossbar node description. It can be host, device, or internal nodes.
''',
    'required': {
        'name': ['s', 'Module instance name'],
        'stub': ['pb', 'Real node or stub.  Stubs only occupy address ranges'],
        'type': [
            's',
            'Module type: {"host", "device", "async", "socket_1n", "socket_m1"}'
        ],
    },
    'optional': {
        'clock': ['s', 'main clock of the port'],
        'reset': ['s', 'main reset of the port'],
        'pipeline': ['pb', 'If true, pipeline is added in front of the port'],
        'req_fifo_pass': ['pb',
                          'If true, pipeline fifo has passthrough behavior on req'],
        'rsp_fifo_pass': ['pb',
                          'If true, pipeline fifo has passthrough behavior on rsp'],
        'inst_type': ['s', 'Instance type'],
        'xbar': ['pb', 'If true, the node is connected to another Xbar'],
        'addr_range': ['lg', addr]
    },
    'added': {}
}

root = {
    'name': 'Top configuration',
    'description': '''
Crossbar configuration format.
''',
    'required': {
        'name': ['s', 'Name of the crossbar'],
        'clock': [
            's', 'Main clock. Internal components use this clock.'
            ' If not specified, it is assumed to be in main clock domain'
        ],
        'reset': ['s', 'Main reset'],
        'connections': [
            'g',
            "List of edge. Key is host, entry in value list is device"
        ],
        'clock_connections': ['g', 'list of clocks'],
        'nodes': ['lg', node]
    },
    'optional': {
        'type': ['s', 'Indicate Hjson type. "xbar" always if exist'],
        'clock_group': ['s', "Remnant from auto-generation scripts. Ignore."],
        'clock_srcs': ['g', "Remnant from auto-generation scripts. Ignore."],
        'domain': ['s', 'Power domain for the crossbar']
    },
    'added': {
        'reset_connections': [
            'g', "Generated by topgen. Key is the reset signal inside IP"
            " and value is the top reset signal"
        ],
    }
}

# Minimum device spacing that is checked during validation
# by inspecting the base addresses. Note that the validation
# script also ensures that base addresses are aligned with
# to this granularity.
MIN_DEVICE_SPACING = 0x1000


def check_keys(obj, control, prefix=""):
    """ Check the keys recursively.

    The control parameter is a control group to check obj data structure.
    """
    error = 0

    # Make sure that every key that we expect has actually been passed.
    for k in control['required'].keys() - obj.keys():
        error += 1
        log.error(prefix + " missing required key: " + k)

    # Check every fields' correctness
    for k, v in obj.items():
        checker = ['', '']
        prefix_name = prefix + " " + k

        if k in control["required"]:
            checker = control["required"][k]
        elif k in control["optional"]:
            checker = control["optional"][k]
        elif k in control["added"]:
            log.warning(prefix + " contains generated key " + k)
            checker = control["added"][k]
        else:
            log.warning(prefix + " contains extra key " + k)
            continue

        # Type and value check
        if checker[0] is not None and checker[0] not in val_types:
            log.error(prefix +
                      " field {} is undefined type. Check val_types {}".format(
                          k, checker[0]))
        if checker[0] is None:
            pass
        elif checker[0] == 'lg':
            # List of subgroup
            error += sum(
                map(
                    partial(check_keys, control=checker[1],
                            prefix=prefix_name), obj[k]))
        elif checker[0] == 'g':
            # if second entry isn't string type, call recursively
            if isinstance(checker[1], str):
                log.info(
                    "Skipping {} as no further control group is given".format(
                        prefix_name))
                continue

            error += check_keys(obj=obj[k],
                                control=checker[1],
                                prefix=prefix_name)

        elif checker[0] == 'd':
            int_v, err = check_int(obj[k], prefix_name)
            if err:
                error += 1

        elif checker[0] == 's' or checker[0] == 't':
            # don't care the string
            pass

        elif checker[0] == 'pb':
            b_v, err = check_bool(obj[k], prefix_name)
            if err:
                error += 1

        elif checker[0] == 'l':
            if not isinstance(obj[k], list):
                error += 1
        else:
            log.error(prefix_name +
                      " is not supported in this configuration format")

    return error


def get_nodetype(t):  # t: str -> NodeType
    if t == "host":
        return NodeType.HOST
    elif t == "device":
        return NodeType.DEVICE
    elif t == "async_fifo":
        return NodeType.ASYNC_FIFO
    elif t == "socket_1n":
        return NodeType.SOCKET_1N
    elif t == "socket_m1":
        return NodeType.SOCKET_M1

    log.error("Cannot process type {}".format(t))
    raise


def checkNameExist(name, xbar):  # name: str -> xbar: Xbar -> bool
    return name.lower() in [x.name for x in xbar.nodes]


def isOverlap(range1, range2):  # Tuple[int,int] -> Tuple[int,int] -> bool
    return not (range2[1] < range1[0] or range2[0] > range1[1])


def isNotMinSpacing(range1, range2):  # Tuple[int,int] -> Tuple[int,int] -> bool
    return not (range2[0] < range1[0] - MIN_DEVICE_SPACING or
                range2[0] >= range1[0] + MIN_DEVICE_SPACING)


def isNotAligned(base):  # Tuple[int,int] -> bool
    return ((base & (MIN_DEVICE_SPACING - 1)) != 0)


# Tuple[int,int] -> List[Tuple[]] -> bool
def checkAddressOverlap(addr, ranges):
    result = [x for x in ranges if isOverlap(x, addr)]
    return len(result) != 0


# Tuple[int,int] -> List[Tuple[]] -> bool
def checkAddressSpacing(addr, ranges):
    result = [x for x in ranges if isNotMinSpacing(x, addr)]
    return len(result) != 0


# this returns 1 if the size mask overlapps with the address base
def checkBaseSizeOverlap(addr_base, size):
    return ((size - 1) & addr_base)


def validate(obj: OrderedDict) -> Xbar:  # OrderedDict -> Xbar
    xbar = Xbar()
    xbar.name = obj["name"].lower()
    xbar.clock = obj["clock"].lower()
    xbar.reset = obj["reset"].lower()
    addr_ranges = []

    obj, err = validate_hjson(obj)  # validate Hjson format first
    if err > 0:
        log.error("Hjson structure error")
        return

    # collection of all clocks and resets of this xbar
    xbar.clocks = [clock for clock in obj["clock_connections"].keys()]
    xbar.resets = [reset for reset in obj["reset_connections"].keys()]

    # Nodes
    for nodeobj in obj["nodes"]:

        if checkNameExist(nodeobj["name"], xbar):
            log.error("Duplicated name: %s" % (nodeobj["name"]))
            raise SystemExit("Duplicated name in the configuration")

        clock = nodeobj["clock"].lower() if "clock" in nodeobj.keys(
        ) else xbar.clock

        reset = nodeobj["reset"].lower() if "reset" in nodeobj.keys(
        ) else xbar.reset

        if clock not in xbar.clocks:
            log.error(
                "Clock %s for module %s does not exist in xbar_%s, check xbar hjson"
                % (clock, nodeobj['name'], obj['name']))
            raise SystemExit("Clock does not exist")

        if reset not in xbar.resets:
            log.error(
                "Reset %s for module %s does not exist in xbar_%s, check xbar hjson"
                % (reset, nodeobj['name'], obj['name']))
            raise SystemExit("Reset does not exist")

        node = Node(name=nodeobj["name"].lower(),
                    node_type=get_nodetype(nodeobj["type"].lower()),
                    clock=clock,
                    reset=reset)

        if node.node_type == NodeType.DEVICE:
            node.xbar = nodeobj["xbar"]
            node.addr_range = []

            # Compact the address ranges
            if node.xbar:
                nodeobj["addr_range"] = simplify_addr(nodeobj, obj)

            for addr in nodeobj["addr_range"]:
                address_from = int(addr["base_addr"], 0)
                size = int(addr["size_byte"], 0)
                address_to = address_from + size - 1

                addr_entry = (address_from, address_to)

                if isNotAligned(address_from):
                    log.error(
                        "Address bases must be aligned to 0x%x blocks. "
                        "Check the config. Addr(0x%x - 0x%x)."
                        % (MIN_DEVICE_SPACING, addr_entry[0], addr_entry[1]))
                    raise SystemExit("Base alignment error occurred")

                if checkBaseSizeOverlap(address_from, size):
                    log.error(
                        "Size mask and base address are overlapping. "
                        " Check the config. Addr(0x%x - 0x%x)"
                        % (addr_entry[0], addr_entry[1]))
                    raise SystemExit("Base/size overlapping error occurred")

                if checkAddressOverlap(addr_entry, addr_ranges):
                    log.error(
                        "Address is overlapping. Check the config. Addr(0x%x - 0x%x). "
                        % (addr_entry[0], addr_entry[1]))
                    raise SystemExit("Address overlapping error occurred")

                if checkAddressSpacing(addr_entry, addr_ranges):
                    log.error(
                        "Address bases must be spaced at least 0x%x apart. "
                        "Check the config. Addr(0x%x - 0x%x)."
                        % (MIN_DEVICE_SPACING, addr_entry[0], addr_entry[1]))
                    raise SystemExit("Address overlapping error occurred")

                addr_ranges.append(addr_entry)
                node.addr_range.append(addr_entry)

        if node.node_type in [NodeType.DEVICE, NodeType.HOST
                              ] and "pipeline" in nodeobj:
            node.pipeline = True if nodeobj["pipeline"] else False
        else:
            node.pipeline = False
        if node.node_type in [NodeType.DEVICE, NodeType.HOST]:
            node.req_fifo_pass = nodeobj["req_fifo_pass"] \
                if "req_fifo_pass" in nodeobj else False

            node.rsp_fifo_pass = nodeobj["rsp_fifo_pass"] \
                if "rsp_fifo_pass" in nodeobj else False

        else:
            node.req_fifo_pass = False
            node.rsp_fifo_pass = False
        xbar.nodes.append(node)

    # Edge
    for host in obj["connections"].keys():
        # host: [device]
        for device in obj["connections"][host]:
            xbar.connect_nodes(host.lower(), device.lower())

    return xbar


def validate_hjson(obj):
    if "type" not in obj:
        obj["type"] = "xbar"
    if "name" not in obj:
        log.error("Component has no name. Aborting.")
        return None, 1

    component = obj["name"]
    error = check_keys(obj, root, component)

    if error > 0:
        log.error("{} has top level error. Aborting".format(component))
        return None, error
    return obj, 0
