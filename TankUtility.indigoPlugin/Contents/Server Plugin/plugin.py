#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import requests
import logging

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
        self.logger.info(u"Starting TankUtility")
        self.tuDevices = {}


    def shutdown(self):
        self.logger.info(u"Shutting down TankUtility")


    def deviceStartComm(self, device):

        self.logger.debug("deviceStartComm: Adding Device %s (%d) to TankUtility device list" % (device.name, device.id))
        assert device.id not in self.tuDevices
        self.tuDevices[device.id] = device
        device.stateListOrDisplayStateIdChanged()
        
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

        self.logger.info(u"Getting tank data from TankUtility server...")
        
        if not self.tuLogin(self.pluginPrefs.get('tuLogin', None), self.pluginPrefs.get('tuPassword')):
            self.logger.debug(u"getDevices: TankUtility Login Failure")
            return

        url =  BASE_URL + 'devices'
        params = { 'token':self.securityToken }
        response = requests.get(url, params=params)
        response.raise_for_status
        
        devices_data = response.json()

        for tuDevice in devices_data['devices']:
        
            url =  BASE_URL + 'devices/' + tuDevice
            params = { 'token':self.securityToken }
            response = requests.get(url, params=params)
            response.raise_for_status

            tank_data = response.json()
            self.logger.debug(u"getDevices: Tank {} data =\n{}\n".format(tuDevice, tank_data))

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

                keyValueList.append({'key': 'owner_name', 'value':   tank_data['device']['name']})
                keyValueList.append({'key': 'tank_address', 'value': tank_data['device']['address']})
                keyValueList.append({'key': 'capacity', 'value':     tank_data['device']['capacity']})
                keyValueList.append({'key': 'fuel_type', 'value':    tank_data['device']['fuelType']})


            tank = tank_data['device']['lastReading']['tank']
            tankStr = "{:.2f} %".format(tank)
            keyValueList.append({'key': 'sensorValue', 'value': tank, 'uiValue': tankStr})

            temperature = tank_data['device']['lastReading']['temperature']
            temperatureStr = "{:.1f} °F".format(temperature)
            keyValueList.append({'key': 'temperature', 'value': temperature, 'uiValue':temperatureStr})

            last_update = float(tank_data['device']['lastReading']['time']) / 1000.0
            timeStr = time.strftime("%a, %d %b %Y %H:%M:%S", time.localtime(last_update))
            keyValueList.append({'key': 'last_update', 'value': timeStr})

            tank_dev.updateStatesOnServer(keyValueList)


    ########################################

    def getDevicesAction(self, pluginAction):
        self.getDevices()

    def doDailyAction(self, pluginAction):

        self.logger.info(u"Performing daily calculations...")
        self.getDevices()
                
        iterator = indigo.devices.iter(filter="self.tankSensor")
        for dev in iterator:

            keyValueList = []

            previous_reading = float(dev.states['previous_reading'])
            self.logger.debug(u"doDaily: previous reading {:.2f} %".format(previous_reading))
            
            current_reading = float(dev.sensorValue)
            self.logger.debug(u"doDaily: current reading {:.2f} %".format(current_reading))
            
            usage = (previous_reading - current_reading) * float(dev.states['capacity'])
            self.logger.debug(u"doDaily: Daily usage {:.2f} gallons".format(usage))
                    
            keyValueList.append({'key': 'daily_usage', 'value': usage})
            keyValueList.append({'key': 'previous_reading', 'value': current_reading})
            dev.updateStatesOnServer(keyValueList)
       
    def doMonthlyAction(self, pluginAction):

        self.logger.info(u"Performing monthly calculations...")
                
        iterator = indigo.devices.iter(filter="self.tankSensor")
        for dev in iterator:

            keyValueList = []
            
            monthly_reading = float(dev.states['monthly_reading'])
            self.logger.debug(u"doMonthly: previous monthly reading {:.2f} %".format(monthly_reading))
            
            current_reading = float(dev.sensorValue)
            self.logger.debug(u"doMonthly: current reading {:.2f} %".format(current_reading))
            
            monthly_usage = (monthly_reading - current_reading) * float(dev.states['capacity'])
            self.logger.debug(u"doMonthly: Monthly usage {:.2f} gallons".format(monthly_usage))
                    
            keyValueList.append({'key': 'monthly_reading', 'value': current_reading})
            keyValueList.append({'key': 'monthly_usage', 'value': monthly_usage})
            dev.updateStatesOnServer(keyValueList)
       
