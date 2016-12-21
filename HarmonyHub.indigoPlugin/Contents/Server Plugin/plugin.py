#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import json
import logging

import sleekxmpp

from ghpu import GitHubPluginUpdater
from HubClient import HubClient

kCurDevVersCount = 0        # current version of plugin devices

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

    def __del__(self):
        indigo.PluginBase.__del__(self)

    def startup(self):
        self.logger.info(u"Starting Harmony Hub")

        self.updater = GitHubPluginUpdater(self)
        self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', 24)) * 60.0 * 60.0
        self.logger.debug(u"updateFrequency = " + str(self.updateFrequency))
        self.next_update_check = time.time()

        self.hubDict = dict()
        self.triggers = { }

    def shutdown(self):
        self.logger.info(u"Shutting down Harmony Hub")


    def runConcurrentThread(self):

        try:
            while True:

                # All hub messages are done in callbacks.  No polling.

                # Plugin Update check

                if (self.updateFrequency > 0.0) and (time.time() > self.next_update_check):
                    self.next_update_check = time.time() + self.updateFrequency
                    self.updater.checkForUpdate()

                self.sleep(60.0)

        except self.stopThread:
            pass

    ####################

    def triggerStartProcessing(self, trigger):
        self.logger.debug("Adding Trigger %s (%d) - %s" % (trigger.name, trigger.id, trigger.pluginTypeId))
        assert trigger.id not in self.triggers
        self.triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        self.logger.debug("Removing Trigger %s (%d)" % (trigger.name, trigger.id))
        assert trigger.id in self.triggers
        del self.triggers[trigger.id]

    def triggerCheck(self, device, eventType):

        # Execute the trigger if it's the right type and for the right hub device

        for triggerId, trigger in sorted(self.triggers.iteritems()):
            self.logger.debug("\tChecking Trigger %s (%s), Type: %s" % (trigger.name, trigger.id, trigger.pluginTypeId))
            if trigger.pluginProps["hubID"] != str(device.id):
                self.logger.debug("\t\tSkipping Trigger %s (%s), wrong hub: %s" % (trigger.name, trigger.id, device.id))
            else:
                if trigger.pluginTypeId != eventType:
                    self.logger.debug("\t\tSkipping Trigger %s (%s), wrong type: %s" % (trigger.name, trigger.id, eventType))
                else:
                    self.logger.debug("\t\tExecuting Trigger %s (%s) on Device %s (%s)" % (trigger.name, trigger.id, device.name ,device.id))
                    indigo.trigger.execute(trigger)


    ####################
    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug(u"validatePrefsConfigUi called")
        errorMsgDict = indigo.Dict()
        try:
            poll = int(valuesDict['updateFrequency'])
            if (poll < 0) or (poll > 24):
                raise
        except:
            errorMsgDict['updateFrequency'] = u"Update frequency is invalid - enter a valid number (between 0 and 24)"
        if len(errorMsgDict) > 0:
            return (False, valuesDict, errorMsgDict)
        return (True, valuesDict)

    ########################################
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(u"logLevel = " + str(self.logLevel))

            self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "24")) * 60.0 * 60.0
            self.logger.debug(u"updateFrequency = " + str(self.updateFrequency))
            self.next_update_check = time.time()


    ########################################
    # Called for each enabled Device belonging to plugin
    #
    def deviceStartComm(self, device):
        self.logger.debug(u'Called deviceStartComm(self, device): %s (%s)' % (device.name, device.id))

        instanceVers = int(device.pluginProps.get('devVersCount', 0))
        self.logger.debug(device.name + u": Device Current Version = " + str(instanceVers))

        if instanceVers >= kCurDevVersCount:
            self.logger.debug(device.name + u": Device Version is up to date")

        elif instanceVers < kCurDevVersCount:
            newProps = device.pluginProps
            newProps["devVersCount"] = kCurDevVersCount

            device.replacePluginPropsOnServer(newProps)
            device.stateListOrDisplayStateIdChanged()
            self.logger.debug(u"deviceStartComm: Updated " + device.name + " to version " + str(kCurDevVersCount))
        else:
            self.logger.error(u"Unknown device version: " + str(instanceVers) + " for device " + device.name)

        if device.id not in self.hubDict:
            self.logger.debug(u"%s: Starting harmonyHub device (%s)" % (device.name, device.id))
            hubClient = HubClient(self, device)
            if (hubClient.ready):
                self.hubDict[device.id] = hubClient
            else:
                self.logger.error(u"%s: Error starting harmonyHub device (%s), disabling..." % (device.name, device.id))
                indigo.device.enable(device, value=False)
                indigo.device.updateStateOnServer(key="serverStatus", value="Disabled")
                indigo.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        else:
            self.logger.error(device.name + u": Duplicate Device ID" )


    ########################################
    # Terminate communication with servers
    #
    def deviceStopComm(self, device):
        self.logger.debug(u'Called deviceStopComm(self, device): %s (%s)' % (device.name, device.id))
        try:
            hubClient = self.hubDict[device.id]
            hubClient.client.disconnect(send_close=True)
            self.hubDict.pop(device.id, None)
        except:
            pass

    ########################################
    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        errorsDict = indigo.Dict()
        if len(errorsDict) > 0:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    ########################################
    def validateActionConfigUi(self, valuesDict, typeId, devId):
        errorsDict = indigo.Dict()
        try:
            pass
        except:
            pass
        if len(errorsDict) > 0:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    ########################################
    # Plugin Actions object callbacks

    def startActivity(self, pluginAction):
        hubDevice = indigo.devices[pluginAction.deviceId]
        if not hubDevice.enabled:
            self.logger.debug(hubDevice.name + u": Can't send Activity commands when hub is not enabled")
            return
        hubClient = self.hubDict[hubDevice.id]
        activityID = pluginAction.props["activity"]
        self.logger.debug(hubDevice.name + u": Start Activity - " + activityID)

        retries = 0
        while retries < 3:
            try:
                hubClient.client.start_activity(int(activityID))
            except sleekxmpp.exceptions.IqTimeout:
                self.logger.debug(hubDevice.name + u": Time out in hub.client.startActivity")
                retries += 1
            except sleekxmpp.exceptions.IqError:
                self.logger.debug(hubDevice.name + u": IqError in hub.client.startActivity")
                return
            else:
                hubClient.current_activity_id = activityID
                return

    def powerOff(self, pluginAction):
        hubDevice = indigo.devices[pluginAction.deviceId]
        if not hubDevice.enabled:
            self.logger.debug(hubDevice.name + u": Can't send Activity commands when hub is not enabled")
            return
        hubClient = self.hubDict[hubDevice.id]
        self.logger.debug(hubDevice.name + u": Power Off")

        retries = 0
        while retries < 3:
            try:
                hubClient.client.start_activity(-1)
            except sleekxmpp.exceptions.IqTimeout:
                self.logger.debug(hubDevice.name + u": Time out in hub.client.startActivity")
                retries += 1
            except sleekxmpp.exceptions.IqError:
                self.logger.debug(hubDevice.name + u": IqError in hub.client.startActivity")
                return
            else:
                hubClient.current_activity_id = "-1"
                return

    def findDeviceForCommand(self, configData, commandName, activityID):
        self.logger.debug(u'findDeviceForCommand: looking for %s in %s' % (commandName, activityID))

        for activity in configData["activity"]:
            if activity["id"] == activityID:
                self.logger.debug(u'findDeviceForCommand:     looking in %s' % (activity["label"]))
                for group in activity["controlGroup"]:
                    self.logger.debug(u'findDeviceForCommand:         looking in %s' % (group["name"]))
                    for function in group['function']:
                        if function['name'] == commandName:
                            action = json.loads(function["action"])
                            device = action["deviceId"]
                            devCommand = action["command"]
                            self.logger.debug(u'findDeviceForCommand:             function %s, device = %s, devCommand = %s' % (function["name"], device, devCommand))
                            return (device, devCommand)
            else:
                self.logger.debug(u'findDeviceForCommand:     skipping %s' % (activity["label"]))

        self.logger.debug(u'findDeviceForCommand: command not found')
        return (None, None)

    def findCommandForDevice(self, configData, commandName, deviceID):
        self.logger.debug(u'findCommandForDevice: looking for %s in %s' % (commandName, deviceID))

        for device in configData["device"]:
            if device["id"] == deviceID:
                self.logger.debug(u'findCommandForDevice:     looking in %s' % (device["label"]))
                for group in device["controlGroup"]:
                    self.logger.debug(u'findCommandForDevice:         looking in %s' % (group["name"]))
                    for function in group['function']:
                        if function['name'] == commandName:
                            action = json.loads(function["action"])
                            devCommand = action["command"]
                            self.logger.debug(u'findCommandForDevice:             function %s, devCommand = %s' % (function["name"], devCommand))
                            return devCommand
            else:
                self.logger.debug(u'findDeviceForCommand:     skipping %s' % (activity["label"]))

        self.logger.debug(u'findCommandForDevice: command not found')
        return None


    def sendCurrentActivityCommand(self, pluginAction):
        hubDevice = indigo.devices[pluginAction.deviceId]
        if not hubDevice.enabled:
            self.logger.debug(hubDevice.name + u": Can't send Activity commands when hub is not enabled")
            return
        hubClient = self.hubDict[hubDevice.id]
        if (int(hubClient.current_activity_id) <= 0):
            self.logger.debug(hubDevice.name + u": Can't send Activity commands when no Activity is running")
            return

        commandName = pluginAction.props["command"]
        if commandName == None:
            self.logger.error(hubDevice.name + u": sendCurrentActivityCommand: command property invalid in pluginProps")
            return

        (device, devCommand) = self.findDeviceForCommand(hubClient.config, commandName, hubClient.current_activity_id)

        if device == None:
            self.logger.warning(hubDevice.name + u": sendCurrentActivityCommand: No command '" + commandName + "' in current activity")
            return

        self.logger.debug(u"%s: sendCurrentActivityCommand: %s (%s) to %s" % (hubDevice.name, commandName, devCommand, device))
        try:
            hubClient.client.send_command(device, devCommand)
        except sleekxmpp.exceptions.IqTimeout:
            self.logger.debug(hubDevice.name + u": Time out in hub.client.send_command")
        except sleekxmpp.exceptions.IqError:
            self.logger.debug(hubDevice.name + u": IqError in hub.client.send_command")
        except Exception as e:
            self.logger.debug(hubDevice.name + u": Error in hub.client.send_command: " + str(e))


    def sendDeviceCommand(self, pluginAction):
        hubDevice = indigo.devices[pluginAction.deviceId]
        if not hubDevice.enabled:
            self.logger.debug(hubDevice.name + u": Can't send commands when hub is not enabled")
            return
        hubClient = self.hubDict[hubDevice.id]

        commandName = pluginAction.props["command"]
        device = pluginAction.props["device"]
        devCommand = self.findCommandForDevice(hubClient.config, commandName, device)

        self.logger.debug(u"%s: sendDeviceCommand: %s (%s) to %s" % (hubDevice.name, commandName, devCommand, device))
        try:
            hubClient.client.send_command(device, devCommand)
        except sleekxmpp.exceptions.IqTimeout:
            self.logger.debug(hubDevice.name + u": Time out in hub.client.send_command")
        except sleekxmpp.exceptions.IqError:
            self.logger.debug(hubDevice.name + u": IqError in hub.client.send_command")
        except Exception as e:
            self.logger.debug(hubDevice.name + u": Error in hub.client.send_command: " + str(e))

    ########################################
    # Menu Methods
    ########################################

    def dumpConfig(self, valuesDict, typeId):
        hubID = int(valuesDict['hubID'])
        config = self.hubDict[hubID].config
        self.logger.info("\n"+json.dumps(config, sort_keys=True, indent=4, separators=(',', ': ')))
        return (True, valuesDict)

    def parseConfig(self, valuesDict, typeId):
        hubID = int(valuesDict['hubID'])
        config = self.hubDict[hubID].config
        for activity in config["activity"]:
            if activity["id"] == "-1":      # skip Power Off
                continue
            self.logger.info(u"Activity: %s, id: %s, order: %i, type: %s, isAVActivity: %s, isTuningDefault: %s" % (activity['label'], activity['id'], activity['activityOrder'], activity['type'], str(activity['isAVActivity']), str(activity['isTuningDefault'])))
            for group in activity["controlGroup"]:
                self.logger.info(u"\tControl Group %s:" % group['name'])
                for function in group['function']:
                    self.logger.info(u"\t\tFunction %s, label: %s, action %s:" % (function['name'], function['label'], function['action']))

        for device in config["device"]:
            self.logger.info(u"Device: %s, id: %s, type: %s, Manufacturer: %s, Model: %s" % (device['label'], device['id'], device['type'], device['manufacturer'], device['model']))
            for group in device["controlGroup"]:
                self.logger.info(u"\tControl Group %s:" % group['name'])
                for function in group['function']:
                    self.logger.info(u"\t\tFunction %s, label: %s, action %s:" % (function['name'], function['label'], function['action']))

        return (True, valuesDict)


    def checkForUpdates(self):
        self.updater.checkForUpdate()

    def updatePlugin(self):
        self.updater.update()

    def forceUpdate(self):
        self.updater.update(currentVersion='0.0.0')

    ########################################
    # ConfigUI methods
    ########################################

    def activityListGenerator(self, filter, valuesDict, typeId, targetId):
        self.logger.debug(u"activityListGenerator: typeId = %s, targetId = %s" % (typeId, targetId))
        retList = []
        config = self.hubDict[targetId].config
        for activity in config["activity"]:
            if activity['id'] != "-1":
                retList.append((activity['id'], activity["label"]))
        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(u"activityListGenerator: %d items returned" % (len(retList)))
        return retList

    def deviceListGenerator(self, filter, valuesDict, typeId, targetId):
        self.logger.debug(u"deviceListGenerator: typeId = %s, targetId = %s" % (typeId, targetId))
        retList = []
        config = self.hubDict[targetId].config
        for device in config["device"]:
            retList.append((device['id'], device["label"]))
        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(u"deviceListGenerator: %d items returned" % (len(retList)))
        return retList

    def commandGroupListGenerator(self, filter, valuesDict, typeId, targetId):
        self.logger.debug(u"commandGroupListGenerator: typeId = %s, targetId = %s" % (typeId, targetId))
        retList = []

        config = self.hubDict[targetId].config

        if typeId == "sendCurrentActivityCommand":
            tempList = []
            for activity in config["activity"]:                 # build a list of all groups found in all activities
                for group in activity["controlGroup"]:
                    tempList.append((group["name"], group["name"]))
            retList = list(set(tempList))                       # get rid of the dupes

        elif typeId == "sendDeviceCommand":
            if not valuesDict:
                return retList
            for device in config["device"]:
                if device["id"] != valuesDict['device']:
                    continue
                for group in device["controlGroup"]:
                    retList.append((group['name'], group["name"]))

        else:
            self.logger.debug(u"commandGroupListGenerator Error: Unknown typeId (%s)" % typeId)

        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(u"commandGroupListGenerator: %d items returned" % (len(retList)))
        return retList

    def commandListGenerator(self, filter, valuesDict, typeId, targetId):
        retList = []
        if not valuesDict:
            return retList

        config = self.hubDict[targetId].config

        if typeId == "sendCurrentActivityCommand":
            self.logger.debug(u"commandListGenerator: typeId = %s, targetId = %s, group = %s" % (typeId, targetId, valuesDict["group"]))
            tempList = []
            for activity in config["activity"]:
                for group in activity["controlGroup"]:
                    if group["name"] != valuesDict['group']:
                        continue                                # build a list of all functions found in the specified controlGroup,
                    for function in group["function"]:          # for all activities (combined)
                        self.logger.debug(u"commandListGenerator: Adding name = '%s', label = '%s'" % (function["name"], function['label']))
                        tempList.append((function["name"], function['name']))
#                        tempList.append((function["name"], function['label'] + ' - ' + function["name"]))
            retList = list(set(tempList))                       # get rid of the dupes

        elif typeId == "sendDeviceCommand":
            self.logger.debug(u"commandListGenerator: typeId = %s, targetId = %s, device = %s" % (typeId, targetId, valuesDict["device"]))
            for device in config["device"]:
                if device["id"] != valuesDict['device']:
                    continue
                for group in device["controlGroup"]:
                    if group["name"] != valuesDict['group']:
                        continue
                    for function in group['function']:
                        self.logger.debug(u"commandListGenerator: Adding name = '%s', label = '%s'" % (function["name"], function['label']))
                        retList.append((function['name'], function["label"]))

        else:
            self.logger.debug(u"commandListGenerator Error: Unknown typeId (%s)" % typeId)

        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(u"commandListGenerator: %d items returned" % (len(retList)))
        return retList

    # doesn't do anything, just needed to force other menus to dynamically refresh

    def menuChanged(self, valuesDict, typeId, devId):
        return valuesDict

    def validateActionConfigUi(self, valuesDict, typeId, actionId):

        errorDict = indigo.Dict()

        if typeId == "startActivity":
            self.logger.debug(u"validateActionConfigUi startActivity")

        elif typeId == "sendCurrentActivityCommand":
            self.logger.debug(u"validateActionConfigUi sendCurrentActivityCommand, group = %s, command = %s" % (valuesDict['group'], valuesDict['command']))

            if valuesDict['group'] == "":
                errorDict["group"] = "Command Group must be selected"
            if valuesDict['command'] == "":
                errorDict["command"] = "Command must be selected"

        elif typeId == "sendDeviceCommand":
            self.logger.debug(u"validateActionConfigUi sendDeviceCommand, device = %s, group = %s, command = %s" % (valuesDict['device'], valuesDict['group'], valuesDict['command']))
            if valuesDict['device'] == "":
                errorDict["device"] = "Device must be selected"
            if valuesDict['group'] == "":
                errorDict["group"] = "Command Group must be selected"
            if valuesDict['command'] == "":
                errorDict["command"] = "Command must be selected"

        else:
            self.logger.debug(u"validateActionConfigUi Error: Unknown typeId (%s)" % typeId)

        if len(errorDict) > 0:
            return (False, valuesDict, errorDict)
        else:
            return (True, valuesDict)


    def pickHub(self, filter=None, valuesDict=None, typeId=0, targetId=0):
        retList =[]
        for id, hubClient in self.hubDict.items():
            hubDevice = indigo.devices[id]
            retList.append((id,hubDevice.name))
        retList.sort(key=lambda tup: tup[1])
        return retList
