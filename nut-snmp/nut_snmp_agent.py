#!/usr/bin/env python3
"""SNMP agent for Tesla UPS Bridge - queries bridge API for Synology DSM compatibility.

This agent implements the IETF UPS MIB (RFC 1628) by querying the bridge's REST API
instead of NUT directly, simplifying the architecture.
"""

import os
import sys
import json
import urllib.request
import urllib.error
from pysnmp.entity import engine, config
from pysnmp.entity.rfc3413 import cmdrsp, context
# Handle both pysnmp 4.x and 7.x API differences
try:
    from pysnmp.carrier.asyncore.dgram import udp
except ImportError:
    from pysnmp.carrier.udp.dgram import udp
from pysnmp.smi import rfc1902

# Environment settings
BRIDGE_API_URL = os.getenv('BRIDGE_API_URL', 'http://localhost:8100/api/status')
SNMP_COMMUNITY = os.getenv('SNMP_COMMUNITY', 'public')
SNMP_PORT = int(os.getenv('SNMP_PORT', '161'))

# Cache for API data
cache = {'data': None, 'timestamp': 0}
CACHE_TTL = 5  # seconds


def query_bridge_api():
    """Query the bridge API for current UPS status."""
    import time
    now = time.time()
    
    # Return cached data if still valid
    if cache['data'] and (now - cache['timestamp']) < CACHE_TTL:
        return cache['data']
    
    try:
        with urllib.request.urlopen(BRIDGE_API_URL, timeout=5) as response:
            data = json.loads(response.read().decode())
            cache['data'] = data
            cache['timestamp'] = now
            return data
    except (urllib.error.URLError, json.JSONDecodeError, Exception) as e:
        print(f"API query failed: {e}", file=sys.stderr)
        # Return fallback data
        return {
            'charge': 85,
            'status': 'online',
            'grid_online': True,
            'providers': [{'name': 'Powerwall', 'status': 'online'}]
        }


# RFC 1628 UPS MIB OID mappings
OID_MAPPINGS = {
    # upsIdent group (33.1.1)
    (1, 3, 6, 1, 2, 1, 33, 1, 1, 1): ('upsIdentManufacturer', 'Tesla'),
    (1, 3, 6, 1, 2, 1, 33, 1, 1, 2): ('upsIdentModel', 'Powerwall'),
    (1, 3, 6, 1, 2, 1, 33, 1, 1, 5): ('upsIdentUPSoftwareVersion', '1.0'),

    # upsBattery group (33.1.2)
    (1, 3, 6, 1, 2, 1, 33, 1, 2, 1): ('upsBatteryStatus', 2),  # 2 = batteryNormal
    (1, 3, 6, 1, 2, 1, 33, 1, 2, 4): ('upsEstimatedChargeRemaining', 85),
    (1, 3, 6, 1, 2, 1, 33, 1, 2, 5): ('upsBatteryVoltage', 500),  # 50.0V * 10
    (1, 3, 6, 1, 2, 1, 33, 1, 2, 6): ('upsBatteryCurrent', 0),
    (1, 3, 6, 1, 2, 1, 33, 1, 2, 7): ('upsBatteryTemperature', 250),  # 25C * 10

    # upsInput group (33.1.3)
    (1, 3, 6, 1, 2, 1, 33, 1, 3, 1): ('upsInputLineIndex', 1),
    (1, 3, 6, 1, 2, 1, 33, 1, 3, 2): ('upsInputFrequency', 600),  # 60Hz * 10
    (1, 3, 6, 1, 2, 1, 33, 1, 3, 3): ('upsInputVoltage', 1200),  # 120V * 10
    (1, 3, 6, 1, 2, 1, 33, 1, 3, 4): ('upsInputCurrent', 0),
    (1, 3, 6, 1, 2, 1, 33, 1, 3, 5): ('upsInputTruePower', 0),

    # upsOutput group (33.1.4)
    (1, 3, 6, 1, 2, 1, 33, 1, 4, 1): ('upsOutputSource', 3),  # 3 = normal
    (1, 3, 6, 1, 2, 1, 33, 1, 4, 2): ('upsOutputFrequency', 600),
    (1, 3, 6, 1, 2, 1, 33, 1, 4, 3): ('upsOutputNumLines', 1),
    (1, 3, 6, 1, 2, 1, 33, 1, 4, 4): ('upsOutputVoltage', 1200),
    (1, 3, 6, 1, 2, 1, 33, 1, 4, 5): ('upsOutputCurrent', 0),
    (1, 3, 6, 1, 2, 1, 33, 1, 4, 6): ('upsOutputPower', 0),
    (1, 3, 6, 1, 2, 1, 33, 1, 4, 7): ('upsOutputPercentLoad', 0),

    # upsAlarm group (33.1.6)
    (1, 3, 6, 1, 2, 1, 33, 1, 6, 1): ('upsAlarmStatus', 0),

    # upsConfig group (33.1.9)
    (1, 3, 6, 1, 2, 1, 33, 1, 9, 1): ('upsConfigAudibleAlarm', 2),
    (1, 3, 6, 1, 2, 1, 33, 1, 9, 3): ('upsConfigLowBatteryTime', 5),
}


def get_oid_value(oid):
    """Get SNMP value for a specific OID."""
    data = query_bridge_api()
    charge = data.get('charge', 85)
    grid_online = data.get('grid_online', True)
    
    # upsEstimatedChargeRemaining (1.3.6.1.2.1.33.1.2.4.0)
    if oid == (1, 3, 6, 1, 2, 1, 33, 1, 2, 4):
        return rfc1902.Integer(int(charge))
    
    # upsBatteryStatus (1.3.6.1.2.1.33.1.2.1.0)
    elif oid == (1, 3, 6, 1, 2, 1, 33, 1, 2, 1):
        if charge < 10:
            return rfc1902.Integer(4)  # batteryDepleted
        elif charge < 20:
            return rfc1902.Integer(3)  # batteryLow
        return rfc1902.Integer(2)  # batteryNormal
    
    # upsOutputSource (1.3.6.1.2.1.33.1.4.1.0)
    elif oid == (1, 3, 6, 1, 2, 1, 33, 1, 4, 1):
        if not grid_online:
            return rfc1902.Integer(5)  # battery
        return rfc1902.Integer(3)  # normal
    
    # Return static values
    value = OID_MAPPINGS.get(oid)
    if value is None:
        return None
    
    _name, val = value
    if isinstance(val, str):
        return rfc1902.OctetString(val)
    return rfc1902.Integer(val)


class SNMPResponder(cmdrsp.GetCommandResponder):
    """SNMP GET responder for UPS MIB."""

    def handleMgmtOperation(self, snmpEngine, stateReference, ctxData, PDU, acInfo):
        from pysnmp.proto.api import v2c
        
        var_binds = []
        for var_bind in v2c.apiPDU.getVarBindList(PDU):
            oid = var_bind[0]
            value = get_oid_value(oid)
            if value is None:
                value = rfc1902.NoSuchObject()
            var_binds.append((oid, value))
        
        self.sendRsp(snmpEngine, stateReference, 0, None, var_binds)
        self.releaseStateInformation(stateReference)


class SNMPNextResponder(cmdrsp.NextCommandResponder):
    """SNMP GETNEXT responder for UPS MIB."""

    def handleMgmtOperation(self, snmpEngine, stateReference, ctxData, PDU, acInfo):
        from pysnmp.proto.api import v2c
        
        var_binds = []
        for var_bind in v2c.apiPDU.getVarBindList(PDU):
            oid = var_bind[0]
            found = False
            for key_oid in sorted(OID_MAPPINGS.keys()):
                if key_oid > oid:
                    value = get_oid_value(key_oid)
                    if value:
                        var_binds.append((key_oid, value))
                        found = True
                        break
            if not found:
                var_binds.append((oid, rfc1902.EndOfMibView()))
        
        self.sendRsp(snmpEngine, stateReference, 0, None, var_binds)
        self.releaseStateInformation(stateReference)


def create_agent():
    """Create and configure SNMP agent."""
    snmp_engine = engine.SnmpEngine()
    
    config.addTransport(
        snmp_engine,
        udp.domainName + (1,),
        udp.UdpTransport().openServerMode(('0.0.0.0', SNMP_PORT))
    )
    
    config.addV1System(snmp_engine, 'my-area', SNMP_COMMUNITY)
    config.addVacmUser(snmp_engine, 2, 'my-area', 'noAuthNoPriv', (1, 3, 6))
    
    snmp_context = context.SnmpContext(snmp_engine)
    
    SNMPResponder(snmp_engine, snmp_context)
    SNMPNextResponder(snmp_engine, snmp_context)
    cmdrsp.SetCommandResponder(snmp_engine, snmp_context)
    cmdrsp.BulkCommandResponder(snmp_engine, snmp_context)
    
    print(f"SNMP agent started on UDP/{SNMP_PORT}")
    print(f"Bridge API: {BRIDGE_API_URL}")
    print(f"Community: {SNMP_COMMUNITY}")
    
    return snmp_engine


if __name__ == '__main__':
    engine = create_agent()
    engine.transportDispatcher.jobStarted(1)
    
    try:
        engine.transportDispatcher.runDispatcher()
    except KeyboardInterrupt:
        engine.transportDispatcher.closeDispatcher()
        print("\nSNMP agent stopped")

