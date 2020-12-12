# From https://forum.pycom.io/topic/3135/air-time-calculation-in-micro-python/2
# LoRaAirTimeCalc.py v0.1 (26/04/2018) for normal Python 3 (for PC) or Pycom MicroPython
# By Roberto Colistete Jr (roberto.colistete at gmail.com)

from network import WLAN, LoRa   # For Pycom MicroPython
#import LoRa   # For Python3
import struct
from math import ceil

# From atom console (pycom)
#from LoRaAirTimeCalc import *
#airtimetheoretical(20, 10, LoRa.BW_125KHZ, LoRa.CODING_4_5)

# Using Pycom constants for bw and cr, calculates the DR (datarate) in bps
def dataratetheoretical(sf, bw, cr):
   if bw == LoRa.BW_125KHZ:
       bwv = 125
   if bw == LoRa.BW_250KHZ:
       bwv = 250
   if bw == LoRa.BW_500KHZ:
       bwv = 500
   crv = 4/(4 + cr)
   return 1000*sf*bwv*(crv)/2**sf

# Air time (in seconds) theoretical calculation for LoRa-RAW, where there is a default preamble of 8 bytes plus 5 bytes of CRC, etc
def airtimetheoretical(payloadsize, sf, bw, cr):
   if bw == LoRa.BW_125KHZ:
       bwv = 125
   if bw == LoRa.BW_250KHZ:
       bwv = 250
   if bw == LoRa.BW_500KHZ:
       bwv = 500
   if sf in [11,12]:
       lowDRopt = 1
   else:
       lowDRopt = 0
   tsym = (2**sf)/(bwv*1000)
   tpreamble = (8 + 4.25)*tsym # Preamble with 8 bytes
   numbersymbolspayload = 8 + max(ceil((8*payloadsize - 4*sf + 28 + 16)/(4*(sf - 2*lowDRopt)))*(4 + cr),0)
   tpayload = numbersymbolspayload*tsym
   tpacket = tpreamble + tpayload
   return tpacket, tpreamble, tpayload, tsym, numbersymbolspayload
