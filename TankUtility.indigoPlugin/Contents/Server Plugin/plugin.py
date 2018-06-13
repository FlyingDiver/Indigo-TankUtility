#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################


import sys
import time
import requests
import logging

from requests.auth import HTTPBasicAuth
from requests.utils import quote

BASE_URL = "https://data.tankutility.com/api/"

################################################################################
class Plugin(indigo.PluginBase):

    ########################################
    # Main Plugin methods
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(u"logLevel = " + str(self.logLevel))
    

    def startup(self):
        indigo.server.log(u"Starting TankUtility")

        self.tuDevices = {}

        self.statusFrequency = float(self.pluginPrefs.get('statusFrequency', "12")) * 60.0 * 60.0
        self.logger.debug(u"statusFrequency = " + str(self.statusFrequency))
        self.next_status_check = time.time()


    def shutdown(self):
        indigo.server.log(u"Shutting down TankUtility")


    def runConcurrentThread(self):

        try:
            while True:

                if time.time() > self.next_status_check:
                    self.getDevices()
                    self.next_status_check = time.time() + self.statusFrequency

                self.sleep(60.0)

        except self.stopThread:
            pass

    def deviceStartComm(self, device):

        self.logger.debug("deviceStartComm: Adding Device %s (%d) to TankUtility device list" % (device.name, device.id))
        assert device.id not in self.tuDevices
        self.tuDevices[device.id] = device

    def deviceStopComm(self, device):
        self.logger.debug("deviceStopComm: Removing Device %s (%d) from TankUtility device list" % (device.name, device.id))
        assert device.id in self.tuDevices
        del self.tuDevices[device.id]

    ########################################
    # ConfigUI methods
    ########################################

    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug(u"validatePrefsConfigUi called")
        errorDict = indigo.Dict()

        try:
            self.logLevel = int(valuesDict[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(u"logLevel = " + str(self.logLevel))

        if len(valuesDict['tuLogin']) < 5:
            errorDict['tuLogin'] = u"Enter your TankUtility login name (email address)"

        if len(valuesDict['tuPassword']) < 1:
            errorDict['tuPassword'] = u"Enter your TankUtility login password"

        if len(errorDict) > 0:
            return (False, valuesDict, errorDict)

        return (True, valuesDict)


    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(u"logLevel = " + str(self.logLevel))

            self.statusFrequency = float(self.pluginPrefs.get('statusFrequency', "10")) * 60.0
            self.logger.debug(u"statusFrequency = " + str(self.statusFrequency))
            self.next_status_check = time.time() + self.statusFrequency

            self.getDevices()

    ########################################

    def actionControlSensor(self, action, dev):

        if action.sensorAction == indigo.kDeviceAction.RequestStatus:
            self.logger.debug(u"actionControlSensor: \"%s\" Request Status" % dev.name)
            self.getDevices()

        else:
            self.logger.error(u"actionControlSensor: \"%s\" Unsupported action requested: %s" % (dev.name, str(action)))


    ########################################


    def tuLogin(self, username=None, password=None):

        if username == None or password == None:
            self.logger.debug(u"tuLogin failure, Username or Password not set")
            return False

        url = BASE_URL + 'getToken'
        try:
            response = requests.get(url, auth=(username, password))
        except requests.exceptions.RequestException as err:
            self.logger.debug(u"tuLogin failure, request url = %s" % (url))
            self.logger.error(u"tuLogin failure, RequestException: %s" % (str(err)))
            self.securityToken = ""
            return False

        if (response.status_code != requests.codes.ok):
            self.logger.debug(u"tuLogin failure, Enum err code %s" % (response.status_code))
            self.securityToken = ""
            return False        

        try:
            data = response.json()
        except:
            self.logger.error(u"tuLogin failure, JSON Decode Error")
            self.securityToken = ""
            return False

        self.securityToken = data['token']
        self.logger.debug(u"tuLogin successful")
        return True

    ########################################

    def getDevices(self):

        
        if not self.tuLogin(self.pluginPrefs.get('tuLogin', None), self.pluginPrefs.get('tuPassword')):
            self.logger.debug(u"getDevices: TankUtility Login Failure")
            return

        url =  BASE_URL + 'devices'
        params = { 'token':self.securityToken }
        response = requests.get(url, params=params)
        response.raise_for_status
        
        devices_data = response.json()
        self.logger.debug(u"getDevices: %d Devices" % len(devices_data['devices']))

        for tuDevice in devices_data['devices']:
        
            url =  BASE_URL + 'devices/' + tuDevice
            params = { 'token':self.securityToken }
            response = requests.get(url, params=params)
            response.raise_for_status

            tank_data = response.json()
            self.logger.debug(u"getDevices:\n{}\n".format(tank_data))

            keyValueList = []

            found = False
            iterator = indigo.devices.iter(filter="self")
            for dev in iterator:
                if dev.address == tuDevice:
                    found = True
                    tank_dev = dev
                    break
                    
            if not found:
                self.logger.debug(u'Unknown TankUtility Device: %s' % (tuDevice))

                try:
                    tank_dev = indigo.device.create(protocol=indigo.kProtocol.Plugin,
                        address=tuDevice,
                        description = "Tank Sensor Device auto-created by TankUtility plugin",
                        deviceTypeId='tankSensor',
                        props={ 'AllowOnStateChange': False,
                                'SupportsOnState': False,
                                'SupportsSensorValue': True,
                                'SupportsStatusRequest': True
                            },
                        name="TankUtility " + tuDevice)
                except Exception as err:
                    self.logger.error(u'Error Creating Sensor Device: %s' % (tuDevice))
                    continue

                keyValueList.append({'key': 'owner_name', 'value': tank_data['device']['name']})
                keyValueList.append({'key': 'tank_address', 'value': tank_data['device']['address']})
                keyValueList.append({'key': 'capacity', 'value': tank_data['device']['capacity']})


            tank = tank_data['device']['lastReading']['tank']
            tankStr = "{:.1f} %".format(tank)
            keyValueList.append({'key': 'sensorValue', 'value': tank, 'uiValue': tankStr})

            temperature = tank_data['device']['lastReading']['temperature']
            temperatureStr = "{:.1f} °F".format(temperature)
            keyValueList.append({'key': 'temperature', 'value': temperature, 'uiValue':temperatureStr})

            keyValueList.append({'key': 'last_update', 'value': tank_data['device']['lastReading']['time_iso']})

            tank_dev.updateStatesOnServer(keyValueList)


    ########################################

