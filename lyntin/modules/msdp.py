#########################################################################
# This file is part of Lyntin.
#
# Lyntin is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# Lyntin is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# copyright (c) 2016 Lex
#
#########################################################################
"""
This module provides support for MSDP protocol.

See reference at http://tintin.sourceforge.net/msdp/

X{msdp_reportable_variables}::

   After MSDP negotiation, we request list of commands and reportable variables supported by the server.
   Then we spam this hook tocollect variables to turn reporting on.

   Arg mapping: { "session": Session, "vars": list, "requested_vars": list }

   session - the Session that this MSDP frame came from

   vars - the list of variable names server supports

   requested_vars - the list of variables to request reporting, filled by hook functions


X{msdp_data}::

   Provides parsed MSDP frame send by the server.

   Arg mapping: { "session": Session, "vars": list }

   session - the Session that this MSDP frame came from

   vars - the list of MSDPVar instances with data


Currently, there is no specific interface tosend MSDP commands from the plugins, except calling session._socket.write withresult of encode_msdp().

   from lyntin.modules import msdp
   data = [msdp.MSDPVar("SEND", "ROOM"), ...]
   session._socket.write(msdp.encode_msdp(data), 0)
"""

from collections import namedtuple
from lyntin import event, exported, net

MSDP = chr(69)
MSDP_VAR = chr(1)
MSDP_VAL = chr(2)
MSDP_TABLE_OPEN = chr(3)
MSDP_TABLE_CLOSE = chr(4)
MSDP_ARRAY_OPEN = chr(5)
MSDP_ARRAY_CLOSE = chr(6)

#: Represents MSDP variable with name and value.
#: MSDP value can be any of string, list of values, or dict with keys as strings and msdp values as values respectively.
MSDPVar = namedtuple('MSDPVar', 'name value')


def encode_msdp(data, toplevel=True):
    result = []
    if isinstance(data, dict):
        result = [MSDP_TABLE_OPEN]
        for k, v in data.iteritems():
            result.append(MSDP_VAR)
            result.append(str(k))
            result.append(MSDP_VAL)
            result.append(encode_msdp(v, False))
        result.append(MSDP_TABLE_CLOSE)
    elif isinstance(data, list) and toplevel:
        result = [net.IAC + net.SB + MSDP]
        for i in data:
            result.append(encode_msdp(i, False))  # should contain MSDPVar items
        result.append(net.IAC + net.SE)
    elif isinstance(data, list) and not toplevel:
        result.append(MSDP_ARRAY_OPEN)
        for i in data:
            result.append(MSDP_VAL + encode_msdp(i, False))
        result.append(MSDP_ARRAY_CLOSE)
    elif isinstance(data, MSDPVar):
        result.append(MSDP_VAR + data.name + MSDP_VAL + encode_msdp(data.value, False))
    else:
        result.append(str(data).replace(net.IAC, net.IAC * 2))
    return ''.join(result)

def _read_msdp_val(text, i):
    if text[i] == MSDP_TABLE_OPEN:
        result, i = _read_msdp_table(text, i + 1)
        if i >= len(text) or not text[i] == MSDP_TABLE_CLOSE:
            raise ValueError("Expecting MSDP_TABLE_CLOSE in position %d" % i)
        return result, i + 1
    elif text[i] == MSDP_ARRAY_OPEN:
        result, i = _read_msdp_array(text, i + 1)
        if i >= len(text) or not text[i] == MSDP_ARRAY_CLOSE:
            raise ValueError("Expecting MSDP_ARRAY_CLOSE in position %d" % i)
        return result, i + 1
    start = i
    while i < len(text):
        if text[i] <= MSDP_ARRAY_CLOSE:
            break
        if text[i] == net.IAC:
            if len(text) > i + 1 and text[i + 1] == net.IAC:
                i += 1  # skip escaped IAC
            else:
                break
        i += 1
    return text[start:i].replace(net.IAC * 2, net.IAC), i

def _read_msdp_table(text, i):
    result = {}
    while i < len(text) and not text[i] == MSDP_TABLE_CLOSE:
        if not text[i] == MSDP_VAR:
            raise ValueError("Expecting MSDP_VAR in position %d" % i)
        i += 1
        start_key = i
        while not text[i] == MSDP_VAL:
            i += 1
        k = text[start_key:i]
        v, i = _read_msdp_val(text, i + 1)
        result[k] = v
    return result, i

def _read_msdp_array(text, i):
    result = []
    while i < len(text) and not text[i] == MSDP_ARRAY_CLOSE:
        if not text[i] == MSDP_VAL:
            raise ValueError("Expecting MSDP_VAL in position %d" % i)
        v, i = _read_msdp_val(text, i + 1)
        result.append(v)
    return result, i

def _read_msdp_var(text, i):
    start = i
    while i < len(text) and not text[i] == MSDP_VAL:
        i += 1
    name = text[start:i]
    value, i = _read_msdp_val(text, i + 1)
    return MSDPVar(name, value), i

def decode_msdp(text):
    if not text.startswith(net.IAC + net.SB + MSDP):
        raise ValueError("Expecting MSDP prologue")
    i = 3
    result = []
    while text[i] == MSDP_VAR:
        var, i = _read_msdp_var(text, i + 1)
        result.append(var)
    if not text[i:] == net.IAC + net.SE:
        raise ValueError("Expecting MSDP epilogue")
    return result

def handle_telnet_option(args):
    data = args['data']
    if not data[2] == MSDP:
        return
    session = args['session']
    if data[1] == net.WILL:  # handshake
        session._socket.write(net.IAC + net.DO + MSDP, 0)
        session._socket.write(encode_msdp([MSDPVar('LIST', 'COMMANDS')]), 0)
    elif data[1] == net.SB:
        try:
            vars = decode_msdp(data)
        except ValueError as e:
            exported.write_error("Failed to decode MSDP frame %r: %s" % (data, e), session)
            return
        for var in vars:
            if var.name == 'COMMANDS':
                if 'REPORT' in var.value:
                    session._socket.write(encode_msdp([MSDPVar('LIST', 'REPORTABLE_VARIABLES')]), 0)
                    break
            elif var.name == 'REPORTABLE_VARIABLES':
                args = exported.hook_spam("msdp_reportable_variables", {"session": session, "vars": var.value, "requested_vars": []})
                if args is None:
                    break
                requested_vars= args["requested_vars"]
                if requested_vars:
                    session._socket.write(''.join(encode_msdp([MSDPVar("REPORT", v)]) for v in requested_vars), 0)
        event.SpamEvent("msdp_data", {'session': session, 'vars': vars}).enqueue()
    raise exported.StopSpammingException

def load():
    exported.hook_register("net_handle_telnet_option", handle_telnet_option)

def unload():
    exported.hook_unregister("net_handle_telnet_option", handle_telnet_option)
