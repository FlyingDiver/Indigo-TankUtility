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
        self.logLevel = int(self.pluginPrefs.get("logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(f"logLevel = {self.logLevel}")

        self.tuDevices = {}
        self.securityToken = None

    def startup(self):
        self.logger.info("Starting TankUtility")

    def shutdown(self):
        self.logger.info("Shutting down TankUtility")

    def deviceStartComm(self, device):

        self.logger.debug(f"deviceStartComm: Adding Device {device.name} ({device.id:d}) to TankUtility device list")
        assert device.id not in self.tuDevices
        self.tuDevices[device.id] = device
        device.stateListOrDisplayStateIdChanged()

    def deviceStopComm(self, device):
        self.logger.debug(f"deviceStopComm: Removing Device {device.name} ({device.id:d}) from TankUtility device list")
        assert device.id in self.tuDevices
        del self.tuDevices[device.id]

    ########################################
    # ConfigUI methods
    ########################################

    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug(u"validatePrefsConfigUi called")
        errorDict = indigo.Dict()

        if len(valuesDict['tuLogin']) < 5:
            errorDict['tuLogin'] = "Enter your TankUtility login name (email address)"

        if len(valuesDict['tuPassword']) < 1:
            errorDict['tuPassword'] = "Enter your TankUtility login password"

        if len(errorDict) > 0:
            return False, valuesDict, errorDict
        return True, valuesDict

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(f"logLevel = {self.logLevel}")

    ########################################

    def actionControlSensor(self, action, dev):

        if action.sensorAction == indigo.kDeviceAction.RequestStatus:
            self.logger.debug(f"actionControlSensor: \"{dev.name}\" Request Status")
            self.getDevices()
        else:
            self.logger.error(f"actionControlSensor: \"{dev.name}\" Unsupported action requested: {action}")

    ########################################

    def tuLogin(self, username=None, password=None):

        if username is None or password is None:
            self.logger.debug("tuLogin failure, Username or Password not set")
            return False

        url = BASE_URL + 'getToken'
        try:
            response = requests.get(url, auth=(username, password))
        except requests.exceptions.RequestException as err:
            self.logger.debug(f"tuLogin failure, request url = {url}, RequestException: {str(err)}")
            self.securityToken = ""
            return False

        if response.status_code != requests.codes.ok:
            self.logger.debug(f"tuLogin failure, Enum err code {response.status_code}")
            self.securityToken = ""
            return False

        try:
            data = response.json()
        except (Exception,):
            self.logger.error("tuLogin failure, JSON Decode Error")
            self.securityToken = ""
            return False

        self.securityToken = data['token']
        self.logger.debug("tuLogin successful")
        return True

    ########################################

    def getDevices(self):

        self.logger.info("Getting tank data from TankUtility server...")

        if not self.tuLogin(self.pluginPrefs.get('tuLogin', None), self.pluginPrefs.get('tuPassword')):
            self.logger.debug("getDevices: TankUtility Login Failure")
            return

        tank_dev = None
        url = BASE_URL + 'devices'
        params = {'token': self.securityToken}
        response = requests.get(url, params=params)
        response.raise_for_status()

        devices_data = response.json()

        for tuDevice in devices_data['devices']:

            url = BASE_URL + 'devices/' + tuDevice
            params = {'token': self.securityToken}
            response = requests.get(url, params=params)
            response.raise_for_status()

            tank_data = response.json()
            self.logger.debug(f"getDevices: Tank {tuDevice} data =\n{tank_data}\n")

            found = False
            iterator = indigo.devices.iter(filter="self")
            for tank_dev in iterator:
                if tank_dev.address == tuDevice:
                    found = True
                    break

            if not found:
                self.logger.debug(f'Unknown TankUtility Device: {tuDevice}')

                try:
                    tank_dev = indigo.device.create(protocol=indigo.kProtocol.Plugin,
                                                    address=tuDevice,
                                                    description="Tank Sensor Device auto-created by TankUtility plugin",
                                                    deviceTypeId='tankSensor',
                                                    props={'AllowOnStateChange': False,
                                                           'SupportsOnState': False,
                                                           'SupportsSensorValue': True,
                                                           'SupportsStatusRequest': True
                                                           },
                                                    name="TankUtility " + tuDevice)
                except Exception as err:
                    self.logger.error(f'Error Creating Sensor Device: {tuDevice}')
                    continue

            keyValueList = [{'key': 'owner_name', 'value': tank_data['device']['name']},
                            {'key': 'tank_address', 'value': tank_data['device']['address']},
                            {'key': 'capacity', 'value': tank_data['device']['capacity']},
                            {'key': 'fuel_type', 'value': tank_data['device']['fuel_type']}]

            tank = tank_data['device']['lastReading']['tank']
            keyValueList.append({'key': 'sensorValue', 'value': tank, 'uiValue': f"{tank:.2f} %"})

            temperature = tank_data['device']['lastReading']['temperature']
            keyValueList.append({'key': 'temperature', 'value': temperature, 'uiValue': f"{temperature:.1f} °F"})

            last_update = float(tank_data['device']['lastReading']['time']) / 1000.0
            timeStr = time.strftime("%a, %d %b %Y %H:%M:%S", time.localtime(last_update))
            keyValueList.append({'key': 'last_update', 'value': timeStr})

            tank_dev.updateStatesOnServer(keyValueList)

    ########################################

    def getDevicesAction(self, pluginAction):
        self.getDevices()

    def doDailyAction(self, pluginAction):

        self.getDevices()  # get an update

        iterator = indigo.devices.iter(filter="self.tankSensor")
        for dev in iterator:
            self.logger.info(f"{dev.name}: Performing daily calculations...")

            state_list = []

            previous_reading = float(dev.states['previous_reading'])
            self.logger.debug(f"doDaily: previous reading {previous_reading:.2f} %")

            current_reading = float(dev.sensorValue)
            self.logger.debug(f"doDaily: current reading {current_reading:.2f} %")

            if current_reading > previous_reading:
                self.logger.debug("doDaily: Tank refilled, resetting")
                usage = 0.0

            else:
                usage = ((previous_reading - current_reading) / 100.0) * float(dev.states['capacity'])

            self.logger.debug(f"doDaily: Daily usage {usage:.2f} gallons")

            current_month_usage = float(dev.states['current_month_usage'])
            self.logger.debug(f"doDaily: Current month usage {current_month_usage:.2f} gallons")

            state_list.append({'key': 'daily_usage', 'value': usage})
            state_list.append({'key': 'previous_reading', 'value': current_reading})
            state_list.append({'key': 'current_month_usage', 'value': (current_month_usage + usage)})
            dev.updateStatesOnServer(state_list)

    def doMonthlyAction(self, pluginAction):

        iterator = indigo.devices.iter(filter="self.tankSensor")
        for dev in iterator:
            self.logger.info(f"{dev.name}: Performing monthly calculations...")

            monthly_reading = float(dev.states['monthly_reading'])
            self.logger.debug(f"doMonthly: previous monthly reading {monthly_reading:.2f} %")

            current_reading = float(dev.sensorValue)
            self.logger.debug(f"doMonthly: current reading {current_reading:.2f} %")

            monthly_usage = float(dev.states['current_month_usage'])
            self.logger.debug(f"doMonthly: Monthly usage {monthly_usage:.2f} gallons")

            state_list = [{'key': 'monthly_reading', 'value': current_reading},
                          {'key': 'monthly_usage', 'value': monthly_usage},
                          {'key': 'current_month_usage', 'value': 0.0}]
            dev.updateStatesOnServer(state_list)
