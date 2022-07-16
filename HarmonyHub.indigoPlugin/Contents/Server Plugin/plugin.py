#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import json
import logging
import threading
import asyncio

try:
    import aioharmony.exceptions
    from aioharmony.harmonyapi import HarmonyAPI, SendCommandDevice
    from aioharmony.responsehandler import Handler
    from aioharmony.const import ClientCallbackType, WEBSOCKETS, XMPP
except ImportError:
    raise ImportError("'Required Python libraries missing.  Run 'pip3 install aioharmony' in Terminal window, then reload plugin. Xcode required!")

class Listener(object):

    def __init__(self, device, client, callback):
        self.device_id = device.id
        self.client_ip = client.ip_address
        self.callback = callback
        client.register_handler(handler=Handler(handler_obj=self.output_response, handler_name='output_response', once=False)) # noqa

    def output_response(self, message):
        message['device_id'] = self.device_id
        message['client_ip'] = self.client_ip
        self.callback(message)


################################################################################
class Plugin(indigo.PluginBase):

    ########################################
    # Main Plugin methods
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)
        self.logLevel = int(pluginPrefs.get("logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(f"logLevel = {self.logLevel}")
        self.protocol = pluginPrefs.get("protocol", WEBSOCKETS)

        self.hub_devices = dict()
        self.activity_devices = dict()
        self.triggers = {}

        self._async_running_clients = dict()
        self._event_loop = None
        self._async_thread = None

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(f"logLevel = {self.logLevel}")
            if valuesDict['protocol'] != self.protocol:
                self.logger.warning("Protocol change requires plugin restart!")

    def startup(self):
        self.logger.info(f"Harmony Hub starting")

        # async thread is used instead of concurrent thread
        self._event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._event_loop)
        self._async_thread = threading.Thread(target=self._run_async_thread)
        self._async_thread.start()

    def shutdown(self):  # noqa
        self.logger.info(f"Harmony Hub stopping")

    def deviceStartComm(self, device):
        self.logger.debug(f"{device.name}: Starting {device.deviceTypeId} device ({device.id})")

        if device.deviceTypeId == "harmonyHub":
            self._event_loop.create_task(self._async_start_device(device))
            self.hub_devices[device.id] = device
        elif device.deviceTypeId == "activityDevice":
            self.activity_devices[device.id] = device.pluginProps['activity']

        else:
            self.logger.error(f"{device.name}: deviceStartComm - Unknown device type: {device.deviceTypeId}")

    def deviceStopComm(self, device):
        self.logger.debug(f"{device.name}: Stopping")

        if device.deviceTypeId == "harmonyHub":
            self._event_loop.create_task(self._async_stop_device(device.address))
            self.hub_devices.pop(device.id, None)
        elif device.deviceTypeId == "activityDevice":
            self.activity_devices.pop(device.id, None)
        else:
            self.logger.error(f"{device.name}: deviceStopComm - Unknown device type: {device.deviceTypeId}")

    ####################

    def triggerStartProcessing(self, trigger):
        self.logger.debug(f"Adding Trigger {trigger.name} ({trigger.id}) - {trigger.pluginTypeId}")
        assert trigger.id not in self.triggers
        self.triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        self.logger.debug(f"Removing Trigger {trigger.name} ({trigger.id})")
        assert trigger.id in self.triggers
        del self.triggers[trigger.id]

    def triggerCheck(self, device, eventType):

        # Execute the trigger if it's the right type and for the right hub device

        for triggerId, trigger in sorted(self.triggers.items()):
            self.logger.threaddebug(f"\tChecking Trigger {trigger.name} ({trigger.id}), Type: {trigger.pluginTypeId}")
            if trigger.pluginProps["hubID"] != str(device.id):
                self.logger.threaddebug(f"\t\tSkipping Trigger {trigger.name} ({trigger.id}), wrong hub: {device.id}")
            else:
                if trigger.pluginTypeId != eventType:
                    self.logger.threaddebug(f"\t\tSkipping Trigger {trigger.name} ({trigger.id}), wrong type: {eventType}")
                else:
                    self.logger.threaddebug(f"\t\tExecuting Trigger {trigger.name} ({trigger.id}) on Device {device.name} ({device.id})")
                    indigo.trigger.execute(trigger)

    ########################################

    def actionControlDimmerRelay(self, action, device):
        hubID = device.pluginProps['hubID']
        activityID = device.pluginProps['activity']
        self.logger.debug(f"{device.name}: actionControlDevice: action: {action.deviceAction}, activity: {activityID}")

        if action.deviceAction == indigo.kDeviceAction.TurnOn:
            self.doActivity(hubID, activityID)

        elif action.deviceAction == indigo.kDeviceAction.TurnOff:
            self.doActivity(hubID, "-1")

        elif action.deviceAction == indigo.kDeviceAction.Toggle:
            if device.onState:
                self.doActivity(hubID, "-1")
            else:
                self.doActivity(hubID, activityID)

        else:
            self.logger.error(f"{device.name}: actionControlDevice: Unsupported action requested: {action}")

    ########################################
    # Plugin Actions object callbacks
    ########################################

    def startActivity(self, pluginAction):
        self.doActivity(pluginAction.deviceId, pluginAction.props["activity"])

    def powerOff(self, pluginAction):
        self.doActivity(pluginAction.deviceId, "-1")

    def doActivity(self, deviceId, activityID):
        self.logger.debug(f"Sending activity {activityID} to hub device {deviceId}")
        client = self._async_running_clients[self.hub_devices[int(deviceId)].address]
        self._event_loop.create_task(self.start_activity(client, int(activityID)))

    ########################################

    def findDeviceForCommand(self, config_data, commandName, activityID):
        self.logger.debug(f'findDeviceForCommand: looking for {commandName} in {activityID}')
        self.logger.threaddebug(f'findDeviceForCommand: config_data =\n{config_data}')

        for activity in config_data["activity"]:
            if activity["id"] != str(activityID):
                self.logger.debug(f'findDeviceForCommand: skipping {activity["label"]}')
            else:
                self.logger.debug(f'findDeviceForCommand: looking in {activity["label"]}')
                for group in activity["controlGroup"]:
                    self.logger.debug(f'findDeviceForCommand: looking in {group["name"]}')
                    for function in group['function']:
                        if function['name'] == commandName:
                            action = json.loads(function["action"])
                            device = action["deviceId"]
                            devCommand = action["command"]
                            self.logger.debug(f'findDeviceForCommand: function {function["name"]}, device = {device}, devCommand = {devCommand}')
                            return device, devCommand

        self.logger.debug('findDeviceForCommand: command not found')
        return None, None

    def findCommandForDevice(self, config_data, command_name, device_id):
        self.logger.debug(f'findCommandForDevice: looking for {command_name} in {device_id}')
        self.logger.threaddebug(f'findCommandForDevice: config_data =\n{config_data}')

        for device in config_data["device"]:
            if device["id"] != str(device_id):
                self.logger.debug(f'findCommandForDevice: skipping {device["label"]}')
            else:
                self.logger.debug(f'findCommandForDevice: looking in {device["label"]}')
                for group in device["controlGroup"]:
                    self.logger.debug(f'findCommandForDevice: looking in {group["name"]}')
                    for function in group['function']:
                        if function['name'] == command_name:
                            action = json.loads(function["action"])
                            devCommand = action["command"]
                            self.logger.debug(f'findCommandForDevice: function {function["name"]}, devCommand = {devCommand}')
                            return devCommand

        self.logger.debug('findCommandForDevice: command not found')
        return None

    ########################################

    def sendCurrentActivityCommand(self, pluginAction):
        hub_device = indigo.devices[pluginAction.deviceId]
        delay = int(pluginAction.props.get("delay", 0))

        if not hub_device.enabled:
            self.logger.debug(f"{ hub_device.name}: Can't send Activity commands when hub is not enabled")
            return
        client = self._async_running_clients[self.hub_devices[hub_device.id].address]
        activity_id, activity_name = client.current_activity
        if int(activity_id) <= 0:
            self.logger.debug(f"{hub_device.name} Can't send Activity commands when no Activity is running")
            return

        command_name = pluginAction.props["command"]
        if command_name is None:
            self.logger.error(f"{hub_device.name}: sendCurrentActivityCommand: command property invalid in pluginProps")
            return

        (device, command) = self.findDeviceForCommand(client.config, command_name, activity_id)

        if device is None:
            self.logger.warning(f"{ hub_device.name}: sendCurrentActivityCommand: No command '{command}' in current activity")
            return

        self.logger.debug(f"{hub_device.name}: sendCurrentActivityCommand: {command_name} ({command}) to {device} with delay {delay}")
        try:
            self._event_loop.create_task(self.send_command(client, device, command, delay))
        except Exception as e:
            self.logger.debug(f"{ hub_device.name}: Error in send_command: {e}")

    def sendDeviceCommand(self, pluginAction):
        hub_device = indigo.devices[pluginAction.deviceId]
        delay = int(pluginAction.props.get("delay",0))

        if not hub_device.enabled:
            self.logger.debug(f"{ hub_device.name}: Can't send commands when hub is not enabled")
            return
        client = self._async_running_clients[self.hub_devices[hub_device.id].address]
        activity_id, activity_name = client.current_activity

        command_name = pluginAction.props["command"]
        device = pluginAction.props["device"]
        command = self.findCommandForDevice(client.config, command_name, device)

        self.logger.debug(f"{hub_device.name}: sendDeviceCommand: {command_name} ({command}) to {device} with delay {delay}")
        try:
            self._event_loop.create_task(self.send_command(client, device, command, delay))
        except Exception as e:
            self.logger.debug(f":{hub_device.name} Error in send_command: {e}")

    ########################################
    # Menu Methods
    ########################################

    def dumpConfig(self, valuesDict, typeId):
        hubID = int(valuesDict['hubID'])
        hub_dev = indigo.devices[hubID]
        self._event_loop.create_task(self.show_config(self._async_running_clients[hub_dev.address]))
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
            config = self._async_running_clients[self.hub_devices[targetId].address].config
        except (Exception,):
            self.logger.error(f"activityListGenerator: targetId {targetId} not in hub list")
            return retList

        for activity in config.get('activity', []):
            if activity['id'] != "-1":
                self.logger.threaddebug(f"activityListGenerator: Adding activity = '{activity['id']}', label = '{activity['label']}'")
                retList.append((activity['id'], activity["label"]))
        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(f"activityListGenerator: {len(retList)} items returned")
        return retList

    def deviceListGenerator(self, filter, valuesDict, typeId, targetId):
        self.logger.debug(f"deviceListGenerator: typeId = {typeId}, targetId = {targetId}")
        retList = []
        config = self._async_running_clients[self.hub_devices[targetId].address].config
        for device in config["device"]:
            self.logger.threaddebug(f"deviceListGenerator: Adding device = '{device['id']}', label = '{device['label']}'")
            retList.append((device['id'], device["label"]))
        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(f"deviceListGenerator: {len(retList)} items returned")
        return retList

    def commandGroupListGenerator(self, filter, valuesDict, typeId, targetId):
        self.logger.debug(f"commandGroupListGenerator: typeId = {typeId}, targetId = {targetId}")
        retList = []

        config = self._async_running_clients[self.hub_devices[targetId].address].config

        if typeId == "sendCurrentActivityCommand":
            tempList = []
            for activity in config["activity"]:  # build a list of all groups found in all activities
                for group in activity["controlGroup"]:
                    self.logger.threaddebug(f"commandGroupListGenerator: Adding name = '{group['name']}', label = '{group['label']}'")
                    tempList.append((group["name"], group["name"]))
            retList = list(set(tempList))  # get rid of the dupes

        elif typeId == "sendActivityCommand":
            tempList = []
            for activity in config["activity"]:  # build a list of all groups found in all activities
                for group in activity["controlGroup"]:
                    self.logger.threaddebug(f"commandGroupListGenerator: Adding name = '{group['name']}', label = '{group['name']}'")
                    tempList.append((group["name"], group["name"]))
            retList = list(set(tempList))  # get rid of the dupes

        elif typeId == "sendDeviceCommand":
            if not valuesDict:
                return retList
            for device in config["device"]:
                if device["id"] != valuesDict['device']:
                    continue
                for group in device["controlGroup"]:
                    self.logger.threaddebug(f"commandGroupListGenerator: Adding name = '{group['name']}', label = '{group['name']}'")
                    retList.append((group['name'], group["name"]))

        else:
            self.logger.debug(f"commandGroupListGenerator Error: Unknown typeId ({typeId})")

        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(f"commandGroupListGenerator: {len(retList)} items returned")
        return retList

    def commandListGenerator(self, filter, valuesDict, typeId, targetId):
        retList = []
        if not valuesDict:
            return retList

        config = self._async_running_clients[self.hub_devices[targetId].address].config

        if typeId == "sendCurrentActivityCommand":
            self.logger.debug(f"commandListGenerator: typeId = {typeId}, targetId = {targetId}, group = {valuesDict['group']}")
            tempList = []
            for activity in config["activity"]:
                for group in activity["controlGroup"]:
                    if group["name"] != valuesDict['group']:
                        continue  # build a list of all functions found in the specified controlGroup,
                    for function in group["function"]:  # for all activities (combined)
                        self.logger.threaddebug(f"commandListGenerator: Adding name = '{function['name']}', label = '{function['label']}'")
                        tempList.append((function["name"], function['name']))
            retList = list(set(tempList))  # get rid of the dupes

        elif typeId == "sendActivityCommand":
            self.logger.debug(f"commandListGenerator: typeId = {typeId}, targetId = {targetId}, group = {valuesDict['group']}")
            tempList = []
            for activity in config["activity"]:
                for group in activity["controlGroup"]:
                    if group["name"] != valuesDict['group']:
                        continue  # build a list of all functions found in the specified controlGroup,
                    for function in group["function"]:  # for all activities (combined)
                        self.logger.threaddebug(f"commandListGenerator: Adding name = '{function['name']}', label = '{function['label']}'")
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
                        self.logger.threaddebug(f"commandListGenerator: Adding name = '{function['name']}', label = '{function['label']}'")
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
            self.logger.debug(f"validateActionConfigUi startActivity, activity = {valuesDict['activity']}")
            if valuesDict['activity'] == "":
                errorDict["activity"] = "Activity must be selected"

        elif typeId == "sendCurrentActivityCommand":
            self.logger.debug(
                f"validateActionConfigUi sendCurrentActivityCommand, group = {valuesDict['group']}, command = {valuesDict['command']}")

            if valuesDict['group'] == "":
                errorDict["group"] = "Command Group must be selected"
            if valuesDict['command'] == "":
                errorDict["command"] = "Command must be selected"

        elif typeId == "sendActivityCommand":
            self.logger.debug(
                f"validateActionConfigUi sendActivityCommand, activity = {valuesDict['activity']}, group = {valuesDict['group']}, command = {valuesDict['command']}")
            if valuesDict['activity'] == "":
                errorDict["activity"] = "Activity must be selected"
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
        for did, hubClient in self.hub_devices.items():
            hubDevice = indigo.devices[did]
            retList.append((did, hubDevice.name))
        retList.sort(key=lambda tup: tup[1])
        return retList

    ########################################

    def _run_async_thread(self):
        self.logger.debug("_run_async_thread starting")
        self._event_loop.create_task(self._async_start())
        # add additional Tasks here as needed
        self._event_loop.run_until_complete(self._async_stop())
        self._event_loop.close()

    async def _async_start(self):
        self.logger.debug("_async_start")

    async def _async_stop(self):
        self.logger.debug("_async_stop waiting")
        while True:
            await asyncio.sleep(1.0)
            if self.stopThread:
                break

    ########################################

    def message_handler(self, message):
        self.logger.threaddebug(f"messageHandler: {message}")

        hub_device = indigo.devices[message['device_id']]
        try:
            message_type = message['type']
        except KeyError:
            self.logger.threaddebug(f"{hub_device.name}: ignoring message has no type: {message}")
            return

        if message_type == "automation.state?notify":
            key = list(message['data'])[0]
            data = message['data'][key]
            self.logger.debug(f"{hub_device.name}: Event automation notify, device: {key}, status: {data['status']}, brightness: {data['brightness']}, on: {data['on']}")
            stateList = [{'key': 'lastAutomationDevice', 'value': key},
                         {'key': 'lastAutomationStatus', 'value': data['status']},
                         {'key': 'lastAutomationBrightness', 'value': str(data['brightness'])},
                         {'key': 'lastAutomationOnState', 'value': str(data['on'])}
                         ]
            hub_device.updateStatesOnServer(stateList)
            broadcastDict = {'lastAutomationDevice': key, 'lastAutomationStatus': data['status'],
                             'lastAutomationBrightness': data['brightness'], 'lastAutomationOnState': data['on'],
                             'hubID': str(hub_device.id)}
            indigo.server.broadcastToSubscribers("automationNotification", broadcastDict)
            self.triggerCheck(hub_device, "automationNotification")

        elif message_type == "harmony.engine?startActivityFinished":
            self.logger.debug(f"{hub_device.name}: Event startActivityFinished, activityId = {message['data']['activityId']}, errorCode = {message['data']['errorCode']}, errorString = {message['data']['errorString']}")

            # update the activity devices
            for deviceId, activityId in self.activity_devices.items():
                device = indigo.devices[deviceId]
                if activityId == message['data']['activityId']:
                    device.updateStateOnServer(key='onOffState', value=True)
                else:
                    device.updateStateOnServer(key='onOffState', value=False)

            # Update the hub's state and send the event to any subscribers
            config = self._async_running_clients[hub_device.address].config
            for activity in config["activity"]:
                if message['data']['activityId'] == activity['id']:
                    stateList = [{'key': 'currentActivityNum', 'value': activity['id']},
                                 {'key': 'currentActivityName', 'value': activity['label']}
                                 ]
                    hub_device.updateStatesOnServer(stateList)
                    broadcastDict = {'currentActivityNum': activity[u'id'], 'currentActivityName': activity['label'],
                                     'hubID': str(hub_device.id)}
                    indigo.server.broadcastToSubscribers(u"activityFinishedNotification", broadcastDict)
                    break
            self.triggerCheck(hub_device, "activityFinishedNotification")

        elif message_type == "connect.stateDigest?notify":
            self.logger.debug(f"{hub_device.name}: Event activityNotification, activityId = {message['data']['activityId']}, activityStatus = {message['data']['activityStatus']}")
            stateList = [{'key': 'notifyActivityId', 'value': message['data']['activityId']},
                         {'key': 'notifyActivityStatus', 'value': message['data']['activityStatus']}
                         ]
            hub_device.updateStatesOnServer(stateList)
            broadcastDict = {'notifyActivityId': message['data']['activityId'], 'notifyActivityStatus': message['data']['activityStatus'], 'hubID': str(hub_device.id)}
            indigo.server.broadcastToSubscribers(u"activityNotification", broadcastDict)
            self.triggerCheck(hub_device, "activityNotification")

        else:
            self.logger.threaddebug(f"{hub_device.name}: ignoring message with unknown type: {message_type}")

    async def _async_start_device(self, device):
        self.logger.debug(f"{device.name}: _async_start_device creating client")
        client = HarmonyAPI(ip_address=device.address, protocol=self.protocol)
        connected = False

        self.logger.debug(f"{device.name}: _async_start_device connecting client")
        try:
            connected = await client.connect()
        except ConnectionRefusedError as e:
            self.logger.debug(f"{device.name}: connect exception: {e}.")
            return

        if not connected:
            self.logger.debug(f"{device.name}: Failed to connect.")
            return

        self.logger.debug(f"{device.name}: Connected to HUB {client.name} ({client.ip_address}) using {client.protocol}")
        self._async_running_clients[device.address] = client

        self.logger.debug(f"{device.name}: Starting listener")
        listener = Listener(device, client, self.message_handler)

    async def _async_stop_device(self, ip_address):
        hub_client = self._async_running_clients[ip_address]
        if not hub_client:
            return

        self.logger.debug(f"{hub_client.name} HUB: Closing connection")
        try:
            await asyncio.wait_for(hub_client.close(), timeout=5)
        except aioharmony.exceptions.TimeOut:
            self.logger.debug(f"{hub_client.name} HUB: Timeout trying to close connection.")

    async def show_config(self, client):
        if client.config:
            self.logger.info(f"HUB: {client.name}\n{json.dumps(client.config, sort_keys=True, indent=4)}")
        else:
            self.logger.warning(f"HUB: {client.name} There was a problem retrieving the configuration")

    async def start_activity(self, client, activity_id=None):
        if activity_id is None:
            self.logger.debug(f"HUB: {client.name} No activity provided to start")
            return

        status = await client.start_activity(activity_id)
        self.logger.debug(f"HUB: {client.name} Start activity {activity_id} returned {status}")

    async def power_off(self, client):
        status = await client.power_off()
        self.logger.debug(f"HUB: {client.name} Power Off returned {status}")

    async def send_command(self, client, device_id, command, delay=0):
        snd_cmd = SendCommandDevice(
            device=device_id,
            command=command,
            delay=delay,
        )
        result_list = await client.send_commands(snd_cmd)
        if result_list:
            for result in result_list:
                self.logger.debug(
                    f"HUB: {client.name} Sending of command {result.command.command} to device {result.command.device} failed with code {result.code}: {result.msg}")
        else:
            self.logger.debug(f"{client.name}: '{command}' command sent")
