import machine
from network import WLAN
import utime
from network import LoRa
import socket
import time
import ubinascii
import crypto
from LoRaAirTimeCalc import *
import sys
from pycoproc import Pycoproc
from microWebCli import MicroWebCli

## PARAMETERS
# Debug messages
debug = 0
# Fixed channel and spreading factor from CARA initial resource block, for testing...
bFixedChannelAndDR=True
# Time to reconnect to Wi-Fi
wifiRetryTime = 20.0
# OTAA or ABP
# VERY IMPORTANT!!! If ABP is used, make sure that RX2 data rate is set to 5
# and RX2 frequency is set to 869.525 MHz (chirpstack -> device profile ->
# -> join (OTAA/ABP))). Set Class-C confirmed downlink timeout to 5 seconds in
# both cases (chirpstack -> device profile -> class-C)
# IMPORTANT!!!: for ABP, first activate the device (before starting this program)
bOTAA = True
# For OTAA
AppEUI = '1234567890ABCDEF' # Not used
AppKey = '00000000000000000000000000000001'
# For ABP
DevAddr = '00000001'
NwkSKey = '00000000000000000000000000000001'
AppSKey = '00000000000000000000000000000001'
# Retransmission time for JOINREQ
joinReqRtxTime = 5.0
# First transmission starting on a CARA period (only for debugging)
bFirstTransmissionStartingOnACARAPeriod = False

# Global variables
selectedFreq = 0
selectedDR = 0

## FUNCTIONS
# General functions
def Random():
  r = crypto.getrandbits(32)
  return ((r[0]<<24)+(r[1]<<16)+(r[2]<<8)+r[3])/4294967295.0

def RandomRange(rfrom, rto):
  return Random()*(rto-rfrom)+rfrom

def zfill(s, width):
  return '{:0>{w}}'.format(s, w=width)

# Functions related to board
def showBoard(lora):
  print("[INFO] Detected board:", sys.platform)

  # Expansion board
  #pyexp = Pycoproc()
  #pid = pyexp.read_product_id()
  #if (pid == 61458):
  #  print("Detected expansion board: PySense")
  #elif (pid == 61459):
  #  print("Detected expansion board: PyTrack")
  #else:
  #  print("Expansion board identifier: ", pid)

  ## WI-FI MAC address
  #print("Device unique ID:", ubinascii.hexlify(machine.unique_id()).upper().decode('utf-8'))
  print("[INFO] Wi-Fi MAC:     ", ubinascii.hexlify(WLAN().mac()[0]).upper().decode('utf-8'))

  ## LORAWAN MAC address
  print("[INFO] LORAWAN DevEUI:", ubinascii.hexlify(lora.mac()).upper().decode('utf-8'))

# Functions related to Wi-Fi
def connectWiFi():
  # Connect to Wi-Fi for synchronizing using NTP
  #print("Trying to connect to Wi-Fi network...")
  wlan = WLAN(mode=WLAN.STA)
  #wlan.connect('ARTEMIS', auth=(WLAN.WPA2, 'wimunet!'))
  wifi_count=1
  while not wlan.isconnected():
  #  machine.idle()
    print('[INFO] Connecting to Wi-Fi, attempt {}...'.format(wifi_count))
    wlan.connect('ARTEMIS', auth=(WLAN.WPA2, 'wimunet!')) #, timeout=5000)
    time.sleep(wifiRetryTime)
    wifi_count = wifi_count + 1

  print('[INFO] WiFi connected')
  print(wlan.ifconfig())

# Functions related to synchronization
def synchronizeTime():

  # Synchronization
  rtc = machine.RTC()
  rtc.ntp_sync('pool.ntp.org', update_period=3600)

  while not rtc.synced():
    machine.idle()

  print("[INFO] RTC NTP sync complete")
  print(rtc.now())

  utime.timezone(7200)
  print("[INFO] Local time:", end=" ")
  print(utime.localtime())

  return rtc

# Functions related to LoRaWAN
def initializeLoRaWAN(randomTimeForJoining):
  timeToWaitForJoining = RandomRange(0,randomTimeForJoining)
  print("[INFO] Time waiting before joining = {:.1f}".format(timeToWaitForJoining))
  time.sleep(timeToWaitForJoining)

  if (bOTAA):
    # Create an OTAA authentication parameters
    app_eui = ubinascii.unhexlify(AppEUI)
    app_key = ubinascii.unhexlify(AppKey)

    # Join a network using OTAA (Over the Air Activation)
    lora.join(activation=LoRa.OTAA, auth=(app_eui, app_key), timeout=0)

  else:
    # Create an ABP authentication params
    dev_addr = struct.unpack(">l", ubinascii.unhexlify(DevAddr))[0]
    nwk_swkey = ubinascii.unhexlify(NwkSKey)
    app_swkey = ubinascii.unhexlify(AppSKey)

    # Join a network using ABP (Activation By Personalization)
    lora.join(activation=LoRa.ABP, auth=(dev_addr, nwk_swkey, app_swkey), timeout=0)

  # Wait until the module has joined the network
  print('[INFO] Not joined yet...')
  while not lora.has_joined():
    #blink(red, 0.5, 1)
    time.sleep(2.5)
    print('[INFO] Not joined yet...')

  print('[INFO] --- Joined Sucessfully --- ')

  # Create a LoRa socket
  s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
  # Set the LoRaWAN data rate (DR0...DR5 - the lower DR, the higher SF)
  s.setsockopt(socket.SOL_LORA, socket.SO_DR, 5)
  # Set CONFIRMED to false
  s.setsockopt(socket.SOL_LORA, socket.SO_CONFIRMED, False)

  return s

def frequencyForChannel(value):
  return (867100000 + value*200000)

def convertDRtoSF(value):
  return (12 - value)

def convertSFtoDR(value):
  return (12 - value)

def setTransmissionParameters(s, selectedFreq, selectedDR):
  if (debug > 0):
    print("[DEBUG] Changing frequency to {:d}".format(selectedFreq))
  # Add all channels with the selected frequency
  for channel in range(0, 15):
    lora.add_channel(channel, frequency=selectedFreq, dr_min=0, dr_max=5)

  # Set spreading factor
  s.setsockopt(socket.SOL_LORA, socket.SO_DR, selectedDR)
  if (debug > 0):
    print("[DEBUG] Changing DR to {:d} (SF={:d})".format(selectedDR, convertDRtoSF(selectedDR)))

def createResourceBlocksLists(sfMask):
  channelsList = []
  sfList = []

  sfMaskStr = bin(sfMask)[2:]
  sfMaskStr = zfill(sfMaskStr, 6)
  #print("sfMask = {}".format(bin(sfMask)))
  if (debug > 0):
    print("[DEBUG] SF mask = {}".format(sfMaskStr))

  i = 0
  for sfIndex in reversed(range(0, len(sfMaskStr))):
    for channel in range(0, 8):
      if (sfMaskStr[sfIndex] == "1"):
        sfList.append(12-sfIndex)
        channelsList.append(frequencyForChannel(channel))
        if (debug > 0):
          print("[DEBUG] Resource block {:d} with channel {:d} and SF {:d}".format(i, channel, 12-sfIndex))
        i = i + 1

  return [channelsList, sfList]

def setDataRate(s, selectedDR):
  # Set spreading factor
  s.setsockopt(socket.SOL_LORA, socket.SO_DR, selectedDR)
  if (debug > 0):
    print("[DEBUG] Changing DR to {:d} (SF={:d})".format(selectedDR, convertDRtoSF(selectedDR)))

def generateMessage(messageCounter):
  if (messageCounter < 10):
    message = "Testing data....." + str(messageCounter)
  elif (messageCounter < 100):
    message = "Testing data...." + str(messageCounter)
  elif (messageCounter < 1000):
    message = "Testing data..." + str(messageCounter)
  elif (messageCounter < 10000):
    message = "Testing data.." + str(messageCounter)
  else:
    message = "Testing data." + str(messageCounter)

  return message

# Functions related to resource blocks
def getCARAParameters():
  contentBytes = MicroWebCli.GETRequest('http://192.168.1.205/CARA/joinTime')
  randomTimeForJoining = float(contentBytes)
  print("[INFO] Random time for joining = {:f}".format(randomTimeForJoining))

  # Time between transmissions = fixedTime + rand(randomTime)
  contentBytes = MicroWebCli.GETRequest('http://192.168.1.205/CARA/fixedTime')
  fixedTime = float(contentBytes)
  print("[INFO] Fixed time between LoRaWAN frames = {:f}".format(fixedTime))
  contentBytes = MicroWebCli.GETRequest('http://192.168.1.205/CARA/randomTime')
  randomTime = float(contentBytes)
  print("[INFO] Ramdom time between LoRaWAN frames = {:f}".format(randomTime))

  # Duration of each period with same transmission parameters (freq and SF)
  # We assume that 48*durationOfPeriod is a divisor of 24h*3600s
  contentBytes = MicroWebCli.GETRequest('http://192.168.1.205/CARA/durationOfPeriod')
  durationOfPeriod = float(contentBytes)
  print("[INFO] Duration of CARA period = {:f}".format(durationOfPeriod))

  # Avoid (or not) border effect (transmissions that spread over two periods)
  contentBytes = MicroWebCli.GETRequest('http://192.168.1.205/CARA/avoidBorderEffect')
  avoidBorderEffect = int(contentBytes)
  print("[INFO] Avoid border effect = {:d}".format(avoidBorderEffect))
  contentBytes = MicroWebCli.GETRequest('http://192.168.1.205/CARA/borderEffectGuardTime')
  borderEffectGuardTime = float(contentBytes)
  print("[INFO] Border effect guard time = {:f}".format(borderEffectGuardTime))

  contentBytes = MicroWebCli.GETRequest('http://192.168.1.205/CARA/count_v2.php')
  countNodes = int(contentBytes)
  print("[INFO] Nodes with version 2 counted = {:d}".format(countNodes))

  return [randomTimeForJoining, fixedTime, randomTime, durationOfPeriod, avoidBorderEffect, borderEffectGuardTime]

def receiveJoinAccept():
  # Waiting for JoinAccept message
  JoinAcceptReceived = False
  # JoinRequest has to be transmitted
  timeToRetransmitJoinReq = True
  while not JoinAcceptReceived:

    if (timeToRetransmitJoinReq):
      s.setblocking(True)
      s.send("#JOINREQ#")
      print("[INFO] #JOINREQ# sent!")
      s.setblocking(False)
      timeToRetransmitJoinReq = False
      timeJoinReq1 = utime.ticks_ms()

    #if (bOTAA):
    if (True):
      data, port = s.recvfrom(64)
    else:
      data = s.recv(64)

    lg = len (data)
    if lg > 0:
      if (debug > 0):
        print("[DEBUG] Downlink Port={:d} Size={:d} Payload={}".format(port, lg, ubinascii.hexlify(data).upper()) )
      strDecodedData = ubinascii.a2b_base64(ubinascii.b2a_base64(data)).decode('utf-8')
      if (debug > 0):
        print("[DEBUG] Downlink Port={:d} Size={:d} Payload={}".format(port, lg, strDecodedData) )

      if strDecodedData.find("#JOINACC#") == 0:
        print ("[INFO] #JOINACC# received")
        JoinAcceptReceived = True
        strDecodedDataSplit = strDecodedData.split()
        caraEnabled = int(strDecodedDataSplit[1])

        if caraEnabled == 1:
          print("[INFO] CARA enabled")
          initialResourceBlock = int(strDecodedDataSplit[2])
          sfMask = int(strDecodedDataSplit[3])

          print("[INFO] Initial resource block = {:d}".format(initialResourceBlock))
          print("[INFO] SF mask = {:d}".format(sfMask))
          #print("SF mask={:d}".format(sfMask))
          channelsList, sfList = createResourceBlocksLists(sfMask)

          selectedSF = sfList[initialResourceBlock]
          selectedDR = convertSFtoDR(selectedSF)

          # Remove all the channels (first three are default channels and cannot be removed)
          for channel in range(0, 15):
            lora.remove_channel(channel)

        else:
          print("[INFO] CARA disabled, using standard LoRaWAN...")
          # If CARA is disabled, the server will use 0...5 as the initial resource block,
          # which will be used to define the DR (i.e. the spreading factor) for each node
          selectedDR = int(strDecodedDataSplit[2]) #[4])
          setDataRate(s, selectedDR)
          print("[INFO] Selected DataRate = {:d}".format(selectedDR))

    time.sleep(0.1)
    timeJoinReq2 = utime.ticks_ms()
    timeFromLastJoinReq = utime.ticks_diff(timeJoinReq2,timeJoinReq1)
    #print("Time (ms) from last transmission of Join Request = {:.3f}".format(timeFromLastJoinReq))
    if (timeFromLastJoinReq > (1000*joinReqRtxTime)):
      timeToRetransmitJoinReq = True

  return [caraEnabled, initialResourceBlock, sfMask, selectedDR, channelsList, sfList]

def assignmentAlgorithm1(timeNextTransmission, channelsList, sfList, initialResourceBlock):
  # THIS ALGORITHM SELECT THE CHANNEL AND SF FOLLOWING A SEQUENTIAL ORDER

  if (debug > 0):
    print("[DEBUG] Time for next transmission (sec) = {:.3f}".format(timeNextTransmission))
  #print("durationOfPeriod = {:.2f}".format(durationOfPeriod))
  indexCurrentPeriod = int(timeNextTransmission / durationOfPeriod)
  if (debug > 0):
    print("[DEBUG] Current period = {:d}".format(indexCurrentPeriod))

  noResourceBlocks = len(channelsList)
  currentResourceBlock = (indexCurrentPeriod+initialResourceBlock) % noResourceBlocks
  selectedFreq = channelsList[currentResourceBlock]
  selectedSF = sfList[currentResourceBlock]
  selectedDR = convertSFtoDR(selectedSF)
  #nextResourceBlock = (indexCurrentPeriod+initialResourceBlock+1) % noResourceBlocks
  #selectedFreqForNextPeriod = channelsList[nextResourceBlock]
  #selectedSFForNextPeriod = sfList[nextResourceBlock]
  #selectedDRForNextPeriod = convertSFtoDR(selectedSFForNextPeriod)

  if (debug > 0):
    print("[DEBUG] Current resource block = {:d}".format(currentResourceBlock))
    print("[DEBUG] Selected frequency = {:d}".format(selectedFreq))
    print("[DEBUG] Selected DR = {:d}".format(selectedDR))

  #print("Next resource block = {:d}".format(nextResourceBlock))
  #print("Selected frequency for next period = {:d}".format(selectedFreqForNextPeriod))
  #print("Selected DR for next period = {:d}".format(selectedDRForNextPeriod))

  #return [selectedFreq, selectedDR, selectedFreqForNextPeriod, selectedDRForNextPeriod]
  return [selectedFreq, selectedDR]

#def checkBorderEffect(timeNextTransmission, selectedFreq, selectedDR, selectedFreqForNextPeriod, selectedDRForNextPeriod, borderEffectGuardTime, payloadsize):
def checkBorderEffect(timeNextTransmission, selectedFreq, selectedDR, borderEffectGuardTime, payloadsize):
  # CHECK TIME OVER AIR TO AVOID BORDER EFFECTS (WAIT FOR NEXT PERIOD IF NECESSARY)

  airTime = airtimetheoretical(payloadsize, convertDRtoSF(selectedDR), LoRa.BW_125KHZ, LoRa.CODING_4_5)[0]
  limitForThisPeriod = (int(timeNextTransmission / durationOfPeriod)+1) * durationOfPeriod
  if (debug > 0):
    print("checkBorderEffect: timeNextTransmission={:.2f}, airTime={:.2f}, limitForThisPeriod={:.2f}".format(timeNextTransmission, airTime, limitForThisPeriod))

  if ( (timeNextTransmission + airTime + borderEffectGuardTime) > limitForThisPeriod ):
    # The transmission has to wait for next period
    #timeNextTransmission = limitForThisPeriod + 0.1
#    timeNextTransmission = timeNextTransmission + airTime + borderEffectGuardTime + 0.1
#    if (debug > 0):
#    print("AVOIDING BORDER EFFECT: timeNextTransmission = {:.3f}".format(timeNextTransmission))
    borderTransmission = True
  else:
    # The transmission can be fitted in the current period
#    print("The transmission can be fitted in the current period")
    borderTransmission = False

#  return timeNextTransmission
  return borderTransmission


###################
## MAIN FUNCTION ##
###################

# INITIALIZE LORA (LORAWAN mode. Europe = LoRa.EU868)
lora = LoRa(mode=LoRa.LORAWAN, region=LoRa.EU868, public=True, tx_retries=3, device_class=LoRa.CLASS_C, adr=False)

# BOARD INFORMATION
showBoard(lora)

# CONNECT TO WIFI
timeToWaitForWiFi = RandomRange(0,10)
time.sleep(timeToWaitForWiFi)

connectWiFi()

## TIME SYNCHRONIZATION
rtc = synchronizeTime()

# OBTAIN EXPERIMENT PARAMETERS
randomTimeForJoining, fixedTime, randomTime, durationOfPeriod, avoidBorderEffect, borderEffectGuardTime = getCARAParameters()

## LORAWAN (initialize and return a socket)
s = initializeLoRaWAN(randomTimeForJoining)

# Waiting for Join Accept message (from CARA server)
caraEnabled, initialResourceBlock, sfMask, selectedDR, channelsList, sfList = receiveJoinAccept()

# Infinite loop
messageCounter = 0
while True:

  message = generateMessage (messageCounter) # Testing data.....01, ...
  payloadsize = len(message)
  messageCounter = messageCounter + 1

  # Time between transmissions
  randNo = fixedTime + RandomRange(0,randomTime)
  if (debug > 0):
    print("[DEBUG] Random number = {:.1f}".format(randNo))

  # Initially we assume that there is no border effect (checked later)
  borderTransmission = False

  if (messageCounter == 1):
    year, month, day, hour, minute, second, usecond, nothing = rtc.now()
    currentTime = hour*3600 + minute*60 + second + usecond/1000000

    if (bFirstTransmissionStartingOnACARAPeriod):
      # In order to start (first message) at the beginning of one period... just for testing
      limitForThisPeriod = (int(currentTime / durationOfPeriod)+1) * durationOfPeriod
      timeNextTransmission = limitForThisPeriod + 1.0
    else:
      # First packet sent at random time
      timeNextTransmission = currentTime + randNo

    selectedFreq, selectedDR = assignmentAlgorithm1(timeNextTransmission, channelsList, sfList, initialResourceBlock)

  else:
    # Not the first packet

    if caraEnabled == 1:
      # Our algorithm for assigning a frequency and a spreading factor for this transmission
      timeNextTransmission = timeLastTransmission + randNo
      selectedFreq, selectedDR = assignmentAlgorithm1(timeNextTransmission, channelsList, sfList, initialResourceBlock)

      # If border effect has to be avoided
      if avoidBorderEffect == 1:
#        timeNextTransmission = checkBorderEffect(timeNextTransmission, selectedFreq, selectedDR, borderEffectGuardTime, payloadsize)
#        selectedFreq, selectedDR = assignmentAlgorithm1(timeNextTransmission, channelsList, sfList, initialResourceBlock)
        borderTransmission = checkBorderEffect(timeNextTransmission, selectedFreq, selectedDR, borderEffectGuardTime, payloadsize)

      # FOR TESTING, FIXED CHANNEL AND DR (OBTAINED FROM CARA - #JOINACC# PARAMETERS)...
      if bFixedChannelAndDR:
        selectedFreq = channelsList[initialResourceBlock]
        selectedSF = sfList[initialResourceBlock]
        selectedDR = convertSFtoDR(selectedSF)

      # Set transmission parameters (frequency and spreading factor)
      setTransmissionParameters(s, selectedFreq, selectedDR)
    # end if (caraEnabled == 1)

  airTime = airtimetheoretical(payloadsize, convertDRtoSF(selectedDR), LoRa.BW_125KHZ, LoRa.CODING_4_5)[0]
  year, month, day, hour, minute, second, usecond, nothing = rtc.now()
  currentTime = hour*3600 + minute*60 + second + usecond/1000000
  #timeToWait = randNo - (currentTime - lastTime) - airTime
  timeToWait = timeNextTransmission - currentTime
  if (debug > 0):
    print("[DEBUG] currentTime = {:.3f}".format(currentTime))
    print("[DEBUG] timeNextTransmission = {:.3f}".format(timeNextTransmission))
    print("[DEBUG] timeToWait = {:.3f}".format(timeToWait))
    print("[DEBUG] airTime = {:.3f}".format(airTime))
  timeLastTransmission = timeNextTransmission

  if (timeToWait > 0):
    print("[INFO] Waiting for next transmission (t={:.3f})...".format(timeNextTransmission))
    time.sleep(timeToWait)
  else:
    print("[INFO] Next transmission starts immediately (time between transmissions too short)!")

  if (borderTransmission == False):
    s.setblocking(True)
    s.send(message)
    s.setblocking(False)
    year, month, day, hour, minute, second, usecond, nothing = rtc.now()
    print("[INFO] Message sent at {:02d}:{:02d}:{:02d}.{:.06d} on {:d} Hz with DR {:d} (air time {:.3f} s)".format(hour, minute, second, usecond, selectedFreq, selectedDR, airTime))
  else:
    year, month, day, hour, minute, second, usecond, nothing = rtc.now()
    print("[INFO] Message not sent at {:02d}:{:02d}:{:02d}.{:.06d} due to border effect".format(hour, minute, second, usecond))
