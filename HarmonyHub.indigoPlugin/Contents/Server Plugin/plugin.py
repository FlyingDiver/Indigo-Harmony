#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import json
import logging

import asyncio

try:
    import aioharmony.exceptions
    from aioharmony.harmonyapi import HarmonyAPI, SendCommandDevice
    from aioharmony.responsehandler import Handler
    from aioharmony.const import ClientCallbackType, WEBSOCKETS, XMPP
except ImportError:
    raise ImportError("'Required Python libraries missing.  Run 'pip3 install aioharmony' in Terminal window, then reload plugin.")

kCurDevVersCount = 1  # current version of plugin devices

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
        self.pluginId = pluginId
        self.hubDict = dict()
        self.activityDict = dict()
        self.triggers = {}

    def startup(self):
        self.logger.info("Starting Harmony Hub")
        indigo.server.subscribeToBroadcast(self.pluginId, "activityFinishedNotification", "activityFinishedHandler")

    def shutdown(self):
        self.logger.info("Shutting down Harmony Hub")

    def activityFinishedHandler(self, broadcastDict):
        self.logger.debug(f"activityFinishedHandler: {broadcastDict['currentActivityName']} ({broadcastDict['currentActivityNum']}) on hub {broadcastDict['hubID']}")

        for activityDevice in self.activityDict.values():
            self.logger.debug(f"Checking activity: {activityDevice.pluginProps['activity']}, hub: {activityDevice.pluginProps['hubID']}")

            if broadcastDict['hubID'] == activityDevice.pluginProps['hubID']:
                if broadcastDict['currentActivityNum'] == activityDevice.pluginProps['activity']:
                    activityDevice.updateStateOnServer(key="onOffState", value=True)
                else:
                    activityDevice.updateStateOnServer(key="onOffState", value=False)

    def runConcurrentThread(self):
        try:
            while True:
                for devID, hub in self.hubDict.items():  # try to make sure all hub devices are connected
                    dev = indigo.devices[devID]
                    try:
                        if not hub.ready:
                            hub.connect(dev)
                    except (Exception,):
                        self.logger.warning(f"{dev.name}: Hub communication error, check XMPP setting.")
                        indigo.device.enable(dev, False)
                self.sleep(60.0)
        except self.StopThread:
            pass

    ####################

    def triggerStartProcessing(self, trigger):
        self.logger.debug(f"Adding Trigger {trigger.name} ({trigger.id:d}) - {trigger.pluginTypeId}")
        assert trigger.id not in self.triggers
        self.triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        self.logger.debug(f"Removing Trigger {trigger.name} ({trigger.id:d})")
        assert trigger.id in self.triggers
        del self.triggers[trigger.id]

    def triggerCheck(self, device, eventType):

        # Execute the trigger if it's the right type and for the right hub device

        for triggerId, trigger in sorted(self.triggers.iteritems()):
            self.logger.debug(f"Checking Trigger {trigger.name} ({trigger.id}), Type: {trigger.pluginTypeId}")
            if trigger.pluginProps["hubID"] != str(device.id):
                self.logger.debug(f"\tSkipping Trigger {trigger.name} ({trigger.id}), wrong hub: {device.id}")
            else:
                if trigger.pluginTypeId != eventType:
                    self.logger.debug(f"\tSkipping Trigger {trigger.name} ({trigger.id}), wrong type: {eventType}")
                else:
                    self.logger.debug(f"\tExecuting Trigger {trigger.name} ({trigger.id}) on Device {device.name} ({device.id})")
                    indigo.trigger.execute(trigger)

    ########################################
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(f"logLevel = {self.logLevel}")

    ########################################
    # Called for each enabled Device belonging to plugin
    #
    def deviceStartComm(self, device):
        self.logger.debug(f'Called deviceStartComm(self, device): {device.name} ({device.id})')

        instanceVers = int(device.pluginProps.get('devVersCount', 0))
        self.logger.debug(f"{device.name}: Device Current Version = {instanceVers}")

        if instanceVers >= kCurDevVersCount:
            self.logger.debug(f"{device.name}: Device Version is up to date")

        elif instanceVers < kCurDevVersCount:
            newProps = device.pluginProps
            newProps["devVersCount"] = kCurDevVersCount

            device.replacePluginPropsOnServer(newProps)
            device.stateListOrDisplayStateIdChanged()
            self.logger.debug(f"deviceStartComm: Updated {device.name} to version {kCurDevVersCount}")
        else:
            self.logger.error(f"Unknown device version: {instanceVers} for device {device.name}")

        if device.deviceTypeId == "harmonyHub":

            if device.id not in self.hubDict:
                self.logger.debug(f"{device.name}: Starting harmonyHub device ({device.id})")
                self.hubDict[device.id] = HubClient(self, device)

            else:
                self.logger.error(f"{device.name}: Duplicate Device ID")

        elif device.deviceTypeId == "activityDevice":
            self.activityDict[device.id] = device

        else:
            self.logger.error(f"{device.name}: deviceStartComm - Unknown device type: {device.deviceTypeId}")

    ########################################
    # Terminate communication with servers
    #
    def deviceStopComm(self, device):
        self.logger.debug(f'Called deviceStopComm(self, device): {device.name} ({device.id})')

        if device.deviceTypeId == "harmonyHub":
            try:
                hubClient = self.hubDict[device.id]
                self.hubDict.pop(device.id, None)
                hubClient.client.disconnect(send_close=True)
            except (Exception,):
                pass

        elif device.deviceTypeId == "activityDevice":
            try:
                self.hubDict.pop(device.id, None)
            except (Exception,):
                pass

        else:
            self.logger.error(f"{device.name}: deviceStopComm - Unknown device type: {device.deviceTypeId}")

    ########################################

    def actionControlDimmerRelay(self, action, dev):
        self.logger.debug(f"{dev.name}: actionControlDevice: action: {action.deviceAction}, activity: {dev.pluginProps['activity']}")

        hubID = dev.pluginProps['hubID']

        if action.deviceAction == indigo.kDeviceAction.TurnOn:
            self.doActivity(hubID, dev.pluginProps['activity'])

        elif action.deviceAction == indigo.kDeviceAction.TurnOff:
            self.doActivity(hubID, "-1")

        elif action.deviceAction == indigo.kDeviceAction.Toggle:
            if dev.onState:
                self.doActivity(hubID, "-1")
            else:
                self.doActivity(hubID, dev.pluginProps['activity'])

        else:
            self.logger.error(f"{dev.name}: actionControlDevice: Unsupported action requested: {action}")

    ########################################
    # Plugin Actions object callbacks

    def startActivity(self, pluginAction):
        self.doActivity(pluginAction.deviceId, pluginAction.props["activity"])

    def powerOff(self, pluginAction):
        self.doActivity(pluginAction.deviceId, "-1")

    def doActivity(self, deviceId, activityID):
        hubDevice = indigo.devices[int(deviceId)]
        if not hubDevice.enabled:
            self.logger.error(f"{hubDevice.name}: Can't send Activity commands when hub is not enabled")
            return
        hubClient = self.hubDict[hubDevice.id]
        self.logger.debug(f"{ hubDevice.name}:Start Activity - " + activityID)

        retries = 0
        while retries < 3:
            try:
                hubClient.client.start_activity(int(activityID))
            except sleekxmpp.exceptions.IqTimeout:
                self.logger.debug(f"{ hubDevice.name}:Time out in hub.client.startActivity")
                retries += 1
            except sleekxmpp.exceptions.IqError:
                self.logger.debug(f"{ hubDevice.name}:IqError in hub.client.startActivity")
                return
            else:
                hubClient.current_activity_id = activityID
                return

    def findDeviceForCommand(self, configData, commandName, activityID):
        self.logger.debug(f'findDeviceForCommand: looking for {commandName} in {activityID}')

        for activity in configData["activity"]:
            if activity["id"] == activityID:
                self.logger.debug(f'findDeviceForCommand:   looking in {activity["label"]}')
                for group in activity["controlGroup"]:
                    self.logger.debug(f'findDeviceForCommand:     looking in {group["name"]}')
                    for function in group['function']:
                        if function['name'] == commandName:
                            action = json.loads(function["action"])
                            device = action["deviceId"]
                            devCommand = action["command"]
                            self.logger.debug(f'findDeviceForCommand:       function {function["name"]}, device = {device}, devCommand = {devCommand}')
                            return device, devCommand
            else:
                self.logger.debug(f'findDeviceForCommand:     skipping {activity["label"]}')

        self.logger.debug('findDeviceForCommand: command not found')
        return None, None

    def findCommandForDevice(self, configData, commandName, deviceID):
        self.logger.debug(f'findCommandForDevice: looking for {commandName} in {deviceID}')

        for device in configData["device"]:
            if device["id"] == deviceID:
                self.logger.debug(f'findCommandForDevice:   looking in {device["label"]}')
                for group in device["controlGroup"]:
                    self.logger.debug(f'findCommandForDevice:     looking in {group["name"]}')
                    for function in group['function']:
                        if function['name'] == commandName:
                            action = json.loads(function["action"])
                            devCommand = action["command"]
                            self.logger.debug(f'findCommandForDevice:       function {function["name"]}, devCommand = {devCommand}')
                            return devCommand
            else:
                self.logger.debug(f'findDeviceForCommand: skipping {device["label"]}')

        self.logger.debug('findCommandForDevice: command not found')
        return None

    def sendCurrentActivityCommand(self, pluginAction):
        hubDevice = indigo.devices[pluginAction.deviceId]
        if not hubDevice.enabled:
            self.logger.debug(f"{ hubDevice.name}: Can't send Activity commands when hub is not enabled")
            return
        hubClient = self.hubDict[hubDevice.id]
        if int(hubClient.current_activity_id) <= 0:
            self.logger.debug(f"{ hubDevice.name} Can't send Activity commands when no Activity is running")
            return

        commandName = pluginAction.props["command"]
        if commandName is None:
            self.logger.error(f"{ hubDevice.name}: sendCurrentActivityCommand: command property invalid in pluginProps")
            return

        (device, devCommand) = self.findDeviceForCommand(hubClient.config, commandName, hubClient.current_activity_id)

        if device is None:
            self.logger.warning(f"{ hubDevice.name}: sendCurrentActivityCommand: No command '{commandName}' in current activity")
            return

        self.logger.debug(f"{hubDevice.name}: sendCurrentActivityCommand: {commandName} ({devCommand}) to {device}")
        try:
            hubClient.client.send_command(device, devCommand)
        except sleekxmpp.exceptions.IqTimeout:
            self.logger.debug(f"{ hubDevice.name}: Time out in hub.client.send_command")
        except sleekxmpp.exceptions.IqError:
            self.logger.debug(f"{ hubDevice.name}: IqError in hub.client.send_command")
        except Exception as e:
            self.logger.debug(f"{ hubDevice.name}: Error in hub.client.send_command: {e}")

    def sendActivityCommand(self, pluginAction):
        hubDevice = indigo.devices[pluginAction.deviceId]
        if not hubDevice.enabled:
            self.logger.debug(f"{ hubDevice.name}: Can't send Activity commands when hub is not enabled")
            return
        hub = self.hubDict[hubDevice.id]
        if int(hub.current_activity_id) <= 0:
            self.logger.debug(f"{ hubDevice.name}: Can't send Activity commands when no Activity is running")
            return

        commandName = pluginAction.props["command"]
        activity = pluginAction.props["activity"]
        device = pluginAction.props["device"]
        devCommand = self.findCommandForDevice(hubClient.config, commandName, device)

        self.logger.debug(f"{hubDevice.name}: sendActivityCommand: {commandName} ({devCommand}) to {device} for {activity}")
        try:
            hub.client.send_command(device, devCommand)
        except sleekxmpp.exceptions.IqTimeout:
            self.logger.debug(f"{ hubDevice.name}: Time out in hub.client.send_command")
        except sleekxmpp.exceptions.IqError:
            self.logger.debug(f"{ hubDevice.name}: IqError in hub.client.send_command")
        except Exception as e:
            self.logger.debug(f"{ hubDevice.name}: Error in hub.client.send_command: {e}")

    def sendDeviceCommand(self, pluginAction):
        hubDevice = indigo.devices[pluginAction.deviceId]
        if not hubDevice.enabled:
            self.logger.debug(f"{ hubDevice.name}: Can't send commands when hub is not enabled")
            return
        hubClient = self.hubDict[hubDevice.id]

        commandName = pluginAction.props["command"]
        device = pluginAction.props["device"]
        devCommand = self.findCommandForDevice(hubClient.config, commandName, device)

        self.logger.debug(f"{hubDevice.name}: sendDeviceCommand: {commandName} ({devCommand}) to {device}")
        try:
            hubClient.client.send_command(device, devCommand)
        except sleekxmpp.exceptions.IqTimeout:
            self.logger.debug(f":{hubDevice.name} Time out in hub.client.send_command")
        except sleekxmpp.exceptions.IqError:
            self.logger.debug(f":{hubDevice.name} IqError in hub.client.send_command")
        except Exception as e:
            self.logger.debug(f":{hubDevice.name} Error in hub.client.send_command: {e}")

    ########################################
    # Menu Methods
    ########################################

    def dumpConfig(self, valuesDict, typeId):
        hubID = int(valuesDict['hubID'])
        config = self.hubDict[hubID].config
        self.logger.info(f"\n{json.dumps(config, sort_keys=True, indent=4, separators=(',', ': '))}")
        return True, valuesDict

    def dumpFormattedConfig(self, valuesDict, typeId):
        hubID = int(valuesDict['hubID'])
        config = self.hubDict[hubID].config
        for activity in config["activity"]:
            if activity["id"] == "-1":  # skip Power Off
                continue
            self.logger.info(u"")
            self.logger.info(
                f"Activity: {activity['label']}, id: {activity['id']}, order: {activity['activityOrder']:d}, type: {activity['type']}, isAVActivity: {str(activity['isAVActivity'])}, isTuningDefault: {str(activity['isTuningDefault'])}")
            for group in activity["controlGroup"]:
                self.logger.info(f"    Control Group {group['name']}:")
                for function in group['function']:
                    self.logger.info(f"        Function {function['name']}: label = '{function['label']}', action: {function['action']}")

        for device in config["device"]:
            self.logger.info(u"")
            self.logger.info(
                f"Device: {device['label']}, id: {device['id']}, type: {device['type']}, Manufacturer: {device['manufacturer']}, Model: {device['model']}")
            for group in device["controlGroup"]:
                self.logger.info(f"    Control Group {group['name']}:")
                for function in group['function']:
                    self.logger.info(f"        Function {function['name']}: label = '{function['label']}', action: {function['action']}")

        return True, valuesDict

    ########################################
    # ConfigUI methods
    ########################################

    def activityListGenerator(self, filter, valuesDict, typeId, targetId):
        self.logger.debug(f"activityListGenerator: typeId = {typeId}, targetId = {targetId}, valuesDict = {valuesDict}")
        retList = []

        if typeId == "activityDevice":
            if len(valuesDict) == 0:  # no hub selected yet
                return retList
            else:
                targetId = int(valuesDict["hubID"])

        try:
            config = self.hubDict[targetId].config
        except (Exception,):
            self.logger.error(f"activityListGenerator: targetId {targetId} not in hubDict")
            return retList

        for activity in config["activity"]:
            if activity['id'] != "-1":
                retList.append((activity['id'], activity["label"]))
        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(f"activityListGenerator: {len(retList):d} items returned")
        return retList

    def deviceListGenerator(self, filter, valuesDict, typeId, targetId):
        self.logger.debug(f"deviceListGenerator: typeId = {typeId}, targetId = {targetId}")
        retList = []
        config = self.hubDict[targetId].config
        for device in config["device"]:
            retList.append((device['id'], device["label"]))
        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(f"deviceListGenerator: {len(retList):d} items returned")
        return retList

    def commandGroupListGenerator(self, filter, valuesDict, typeId, targetId):
        self.logger.debug(f"commandGroupListGenerator: typeId = {typeId}, targetId = {targetId}")
        retList = []

        config = self.hubDict[targetId].config

        if typeId == "sendCurrentActivityCommand":
            tempList = []
            for activity in config["activity"]:  # build a list of all groups found in all activities
                for group in activity["controlGroup"]:
                    tempList.append((group["name"], group["name"]))
            retList = list(set(tempList))  # get rid of the dupes

        elif typeId == "sendDeviceCommand":
            if not valuesDict:
                return retList
            for device in config["device"]:
                if device["id"] != valuesDict['device']:
                    continue
                for group in device["controlGroup"]:
                    retList.append((group['name'], group["name"]))

        else:
            self.logger.debug(f"commandGroupListGenerator Error: Unknown typeId ({typeId})")

        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(f"commandGroupListGenerator: {len(retList):d} items returned")
        return retList

    def commandListGenerator(self, filter, valuesDict, typeId, targetId):
        retList = []
        if not valuesDict:
            return retList

        config = self.hubDict[targetId].config

        if typeId == "sendCurrentActivityCommand":
            self.logger.debug(f"commandListGenerator: typeId = {typeId}, targetId = {targetId}, group = {valuesDict['group']}")
            tempList = []
            for activity in config["activity"]:
                for group in activity["controlGroup"]:
                    if group["name"] != valuesDict['group']:
                        continue  # build a list of all functions found in the specified controlGroup,
                    for function in group["function"]:  # for all activities (combined)
                        self.logger.debug(f"commandListGenerator: Adding name = '{function['name']}', label = '{function['label']}'")
                        tempList.append((function["name"], function['name']))
            retList = list(set(tempList))  # get rid of the dupes

        elif typeId == "sendDeviceCommand":
            self.logger.debug(f"commandListGenerator: typeId = {typeId}, targetId = {targetId}, device = {valuesDict['device']}")
            for device in config["device"]:
                if device["id"] != valuesDict['device']:
                    continue
                for group in device["controlGroup"]:
                    if group["name"] != valuesDict['group']:
                        continue
                    for function in group['function']:
                        self.logger.debug(f"commandListGenerator: Adding name = '{function['name']}', label = '{function['label']}'")
                        retList.append((function['name'], function["label"]))

        else:
            self.logger.debug(f"commandListGenerator Error: Unknown typeId ({typeId})")

        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(f"commandListGenerator: {len(retList):d} items returned")
        return retList

    # doesn't do anything, just needed to force other menus to dynamically refresh

    @staticmethod
    def menuChanged(valuesDict, typeId, devId):
        return valuesDict

    def validateActionConfigUi(self, valuesDict, typeId, actionId):

        errorDict = indigo.Dict()

        if typeId == "startActivity":
            self.logger.debug("validateActionConfigUi startActivity")

        elif typeId == "sendCurrentActivityCommand":
            self.logger.debug(
                f"validateActionConfigUi sendCurrentActivityCommand, group = {valuesDict['group']}, command = {valuesDict['command']}")

            if valuesDict['group'] == "":
                errorDict["group"] = "Command Group must be selected"
            if valuesDict['command'] == "":
                errorDict["command"] = "Command must be selected"

        elif typeId == "sendDeviceCommand":
            self.logger.debug(
                f"validateActionConfigUi sendDeviceCommand, device = {valuesDict['device']}, group = {valuesDict['group']}, command = {valuesDict['command']}")
            if valuesDict['device'] == "":
                errorDict["device"] = "Device must be selected"
            if valuesDict['group'] == "":
                errorDict["group"] = "Command Group must be selected"
            if valuesDict['command'] == "":
                errorDict["command"] = "Command must be selected"

        else:
            self.logger.debug(f"validateActionConfigUi Error: Unknown typeId ({typeId})")

        if len(errorDict) > 0:
            return False, valuesDict, errorDict
        else:
            return True, valuesDict

    def pickHub(self, filter=None, valuesDict=None, typeId=0, targetId=0):
        retList = []
        for did, hubClient in self.hubDict.items():
            hubDevice = indigo.devices[did]
            retList.append((did, hubDevice.name))
        retList.sort(key=lambda tup: tup[1])
        return retList
