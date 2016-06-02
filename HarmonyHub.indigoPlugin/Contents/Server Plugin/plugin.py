#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import sys
import time
import json
import sleekxmpp
from sleekxmpp.xmlstream import ET
from sleekxmpp.xmlstream.matcher.base import MatcherBase
from sleekxmpp.xmlstream.handler import Callback

from ghpu import GitHubPluginUpdater
from harmony import auth
from harmony import client as harmony_client

kCurDevVersCount = 0		# current version of plugin devices

class MatchMessage(MatcherBase):
	def __init__(self, criteria):
		self._criteria = criteria

	def match(self, xml):
	
		if type(xml) == sleekxmpp.stanza.stream_features.StreamFeatures:
			return False
		elif type(xml) == sleekxmpp.features.feature_mechanisms.stanza.success.Success:
			return False
		elif type(xml) == sleekxmpp.stanza.iq.Iq:
			return False
		elif type(xml) == sleekxmpp.stanza.message.Message:
			return True
		else:
			indigo.server.log(u"MatchMessage: %s" % type(xml))
			return False

class HubClient(object):

	def __init__(self, plugin, device):
		self.plugin = plugin
		self.device = device
		self.activityList = dict()
		
		self.harmony_ip = device.pluginProps['address']
		self.harmony_port = 5222
	
		self.auth_token = auth.login(device.pluginProps['harmonyLogin'], device.pluginProps['harmonyPassword'])
		if not self.auth_token:
			self.plugin.debugLog(device.name + u': Could not get token from Logitech server.')

		try:	
			self.auth_token = auth.login(device.pluginProps['harmonyLogin'], device.pluginProps['harmonyPassword'])
			if not self.auth_token:
				self.plugin.debugLog(device.name + u': Could not get token from Logitech server.')

			self.session_token = auth.swap_auth_token(self.harmony_ip, self.harmony_port, self.auth_token)
			if not self.session_token:
				self.plugin.debugLog(device.name + u': Could not swap login token for session token.')

			self.client = harmony_client.HarmonyClient(self.session_token)
			self.client.registerHandler(Callback('Hub Message Handler', MatchMessage(''), self.messageHandler))

			self.client.connect(address=(self.harmony_ip, self.harmony_port), use_tls=False, use_ssl=False)
			self.client.process(block=False)
			while not self.client.sessionstarted:
				self.plugin.debugLog(self.device.name + u": Waiting for client.sessionstarted")
				time.sleep(0.1)
		except Exception as e:
			self.plugin.debugLog(self.device.name + u": Error setting up hub connection: " + str(e))
			
		try:	
			self.config = self.client.get_config()
		except Exception as e:
			self.plugin.debugLog(self.device.name + u": Error in client.get_config: " + str(e))
			
		try:	
			self.current_activity_id = str(self.client.get_current_activity())
		except sleekxmpp.exceptions.IqTimeout:
			self.plugin.debugLog(self.device.name + u": Time out in client.get_current_activity")
			self.current_activity_id = 0
		except sleekxmpp.exceptions.IqError:
			self.plugin.debugLog(self.device.name + u": IqError in client.get_current_activity")
			self.current_activity_id = 0
		except Exception as e:
			self.plugin.debugLog(self.device.name + u": Error in client.get_current_activity: " + str(e))
			self.current_activity_id = 0
			
		for activity in self.config["activity"]:
			if activity["id"] == "-1":
				if '-1' == self.current_activity_id:
					self.device.updateStateOnServer(key="currentActivityNum", value=activity[u'id'])
					self.device.updateStateOnServer(key="currentActivityName", value=activity[u'label'])

			else:
				try:
					action = json.loads(activity["controlGroup"][0]["function"][0]["action"])			
					soundDev = action["deviceId"]						
					self.activityList[activity[u'id']] = {'label': activity[u'label'], 'type': activity[u'type'], 'soundDev': soundDev }

				except Exception as e:			# Not all Activities have sound devices...
					self.activityList[activity[u'id']] = {'label': activity[u'label'], 'type': activity[u'type'] }

				if activity[u'id'] == self.current_activity_id:
					self.device.updateStateOnServer(key="currentActivityNum", value=activity[u'id'])
					self.device.updateStateOnServer(key="currentActivityName", value=activity[u'label'])

				self.plugin.debugLog(device.name + u": Activity: %s (%s)" % (activity[u'label'], activity[u'id']))

		self.plugin.debugLog(self.device.name + u": current_activity_id = " + self.current_activity_id)


	def messageHandler(self, data):
		root = ET.fromstring(str(data))
		for child in root:
			if "event" in child.tag:
				if "notify" in str(child.attrib):
					if "connect.stateDigest" in str(child.attrib):
						try:
							content = json.loads(child.text)
						except Exception as e:
							self.plugin.errorLog(self.device.name + u": Event state notify child.text parse error = %s" % str(e))
							self.plugin.errorLog(self.device.name + u": Event state notify child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
						else:
							self.plugin.debugLog(self.device.name + u": messageHandler: Event state notify, activityId = %s, activityStatus = %s" % (content['activityId'], content['activityStatus']))
							self.device.updateStateOnServer(key="notifyActivityId", value=content['activityId'])
							self.device.updateStateOnServer(key="notifyActivityStatus", value=content['activityStatus'])
							self.plugin.triggerCheck(self.device, "activityNotification")

					elif "automation.state" in str(child.attrib):
						self.plugin.debugLog(self.device.name + u": messageHandler: Event automation notify, contents:")
						try:
							content = json.loads(child.text)
						except Exception as e:
							self.plugin.errorLog(self.device.name + u": Event automation notify child.text parse error = %s" % str(e))
							self.plugin.errorLog(self.device.name + u": Event automation notify child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
						else:
							for key, device in content.items():
								self.plugin.debugLog(self.device.name + u": Device: %s, status: %s, brightness: %i, on: %r" % (key, device['status'], device['brightness'], device['on']))
								self.device.updateStateOnServer(key="lastAutomationDevice", value=key)
								self.device.updateStateOnServer(key="lastAutomationStatus", value=device['status'])
								self.device.updateStateOnServer(key="lastAutomationBrightness", value=str(device['brightness']))
								self.device.updateStateOnServer(key="lastAutomationOnState", value=str(device['on']))
								self.plugin.triggerCheck(self.device, "automationNotification")
					else:
						self.plugin.errorLog(self.device.name + u": messageHandler: Unknown Event Type: %s\n%s" % (child.attrib, child.text))
									
				elif "startActivityFinished" in str(child.attrib):
					try:
						pairs = child.text.split(':')
						activityId = pairs[0].split('=')
						errorCode = pairs[1].split('=')
						errorString = pairs[2].split('=')
					except Exception as e:
						self.plugin.errorLog(self.device.name + u": Event startActivityFinished child.text parse error = %s" % str(e))
						self.plugin.errorLog(self.device.name + u": Event startActivityFinished child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
					else:
						self.plugin.debugLog(self.device.name + u": messageHandler: Event startActivityFinished, activityId = %s, errorCode = %s, errorString = %s" % (activityId[1], errorCode[1], errorString[1]))
						for activity in self.config["activity"]:
							if activityId[1] == activity[u'id']:
								self.device.updateStateOnServer(key="currentActivityNum", value=activity[u'id'])
								self.device.updateStateOnServer(key="currentActivityName", value=activity[u'label'])
								self.plugin.triggerCheck(self.device, "activityNotification")
								break	

				elif "pressType" in str(child.attrib):
					try:
						pressType = child.text.split('=')
						self.plugin.debugLog(self.device.name + u": messageHandler: Event pressType, Type = %s" % pressType[1])
					except Exception as e:
						self.plugin.errorLog(self.device.name + u": Event pressType child.text parse error = %s" % str(e))
						self.plugin.errorLog(self.device.name + u": Event pressType child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))

				elif "startActivity" in str(child.attrib):
					try:
						pairs = child.text.split(':')
						done = pairs[0].split('=')
						total = pairs[1].split('=')
						deviceId = pairs[2].split('=')
					except Exception as e:
						self.plugin.errorLog(self.device.name + u": Event startActivity child.text parse error = %s" % str(e))
						self.plugin.errorLog(self.device.name + u": Event startActivity child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
					else:
						self.plugin.debugLog(self.device.name + u": messageHandler: Event startActivity, done = %s, total = %s, deviceId = %s" % (done[1], total[1], deviceId[1]))

				else:
					self.plugin.errorLog(self.device.name + u": messageHandler: Unknown Event Type: %s\n%s" % (child.attrib, child.text))
			
			else:
				self.plugin.errorLog(self.device.name + u": messageHandler: Unknown Message Type: " + child.tag)
				
			
	
################################################################################
class Plugin(indigo.PluginBase):
					
	########################################
	# Main Plugin methods
	########################################
	def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
		indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
		
		self.debug = self.pluginPrefs.get(u"showDebugInfo", False)
		self.debugLog(u"Debugging enabled")

	def __del__(self):
		indigo.PluginBase.__del__(self)

	def startup(self):
		indigo.server.log(u"Starting Harmony Hub")
		
		self.updater = GitHubPluginUpdater(self)
		self.updater.checkForUpdate()
		self.updateFrequency = self.pluginPrefs.get('updateFrequency', 24)
		if self.updateFrequency > 0:
			self.next_update_check = time.time() + float(self.updateFrequency) * 60.0 * 60.0

		self.hubDict = dict()
		self.triggers = { }
							
	def shutdown(self):
		indigo.server.log(u"Shutting down Harmony Hub")


	def runConcurrentThread(self):

		self.next_poll = 0.0
		
		try:
			while True:
				
				# All hub messages are done in callbacks.  No polling.
				
				# Plugin Update check
				
				if self.updateFrequency > 0:
					if time.time() > self.next_update_check:
						self.updater.checkForUpdate()
						self.next_update_check = time.time() + float(self.pluginPrefs['updateFrequency']) * 60.0 * 60.0

				self.sleep(1.0) 
								
		except self.stopThread:
			pass
							

	####################

	def getDeviceConfigUiValues(self, pluginProps, typeId, devId):
		self.debugLog("getDeviceConfigUiValues, typeID = " + typeId)
		valuesDict = indigo.Dict(pluginProps)
		errorsDict = indigo.Dict()
		return (valuesDict, errorsDict)
	  
	
	####################

	def triggerStartProcessing(self, trigger):
		self.debugLog("Adding Trigger %s (%d) - %s" % (trigger.name, trigger.id, trigger.pluginTypeId))
		assert trigger.id not in self.triggers
		self.triggers[trigger.id] = trigger
 
	def triggerStopProcessing(self, trigger):
		self.debugLog("Removing Trigger %s (%d)" % (trigger.name, trigger.id))
		assert trigger.id in self.triggers
		del self.triggers[trigger.id] 
		
	def triggerCheck(self, device, eventType):
#		self.debugLog("Checking %d Triggers for Device: %s (%s), Type: %s" % (len(self.triggers), device.name, device.id, eventType))

		# Execute the trigger if it's the right type and for the right hub device
			
		for triggerId, trigger in sorted(self.triggers.iteritems()):
			self.debugLog("\tChecking Trigger %s (%s), Type: %s" % (trigger.name, trigger.id, trigger.pluginTypeId))
			if trigger.pluginProps["hubID"] != str(device.id):
				self.debugLog("\t\tSkipping Trigger %s (%s), wrong hub: %s" % (trigger.name, trigger.id, device.id))
			else:
				if trigger.pluginTypeId != eventType:
					self.debugLog("\t\tSkipping Trigger %s (%s), wrong type: %s" % (trigger.name, trigger.id, eventType))
				else:
					self.debugLog("\t\tExecuting Trigger %s (%s) on Device %s (%s)" % (trigger.name, trigger.id, device.name ,device.id))
					indigo.trigger.execute(trigger)
			
	
			
	
	####################
	def validatePrefsConfigUi(self, valuesDict):
		self.debugLog(u"validatePrefsConfigUi called")
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
			self.debug = valuesDict.get("showDebugInfo", False)
			if self.debug:
				self.debugLog(u"Debug logging enabled")
			else:
				self.debugLog(u"Debug logging disabled")

	########################################
	# Called for each enabled Device belonging to plugin
	# Verify connectivity to servers and start polling IMAP/POP servers here
	#
	def deviceStartComm(self, device):
						
#		instanceVers = int(device.pluginProps.get('devVersCount', 0))
#		self.debugLog(device.name + u": Device Current Version = " + str(instanceVers))

#		if instanceVers >= kCurDevVersCount:
#			self.debugLog(device.name + u": Device Version is up to date")
			
#		elif instanceVers < kCurDevVersCount:
#			newProps = device.pluginProps

#		else:
#			self.errorLog(u"Unknown device version: " + str(instanceVers) + " for device " + device.name)					
			
		if len(device.pluginProps) < 3:
			self.errorLog(u"Server \"%s\" is misconfigured - disabling" % device.name)
			indigo.device.enable(device, value=False)
				
		else:			
			if int(device.id) not in self.hubDict:
				if device.deviceTypeId == "harmonyHub":
					self.debugLog(u"%s: Starting harmonyHub device (%s)" % (device.name, device.id))
					self.hubDict[int(device.id)] = HubClient(self, device)			
					
				else:
					self.errorLog(u"Unknown server device type: " + str(device.deviceTypeId))					

			else:
				self.debugLog(device.name + u": Duplicate Device ID" )
			
	########################################
	# Terminate communication with servers
	#
	def deviceStopComm(self, device):
		client= self.hubDict[int(device.id)].client
		client.disconnect(send_close=True)
		
 
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
		hub = self.hubDict[int(hubDevice.id)]
		activityID = pluginAction.props["activity"]
		activityLabel = hub.activityList[activityID]["label"]
		self.debugLog(hubDevice.name + u": Start Activity - " + activityLabel)
		hub.client.start_activity(int(activityID))
		hub.device.updateStateOnServer(key="currentActivityNum", value=activityID)
		hub.device.updateStateOnServer(key="currentactivityName", value=activityLabel)
		self.triggerCheck(hub.device)

	def powerOff(self, pluginAction):
		hubDevice = indigo.devices[pluginAction.deviceId]
		hub = self.hubDict[int(hubDevice.id)]
		self.debugLog(hubDevice.name + u": Power Off")
		hub.client.start_activity(-1)
		hub.device.updateStateOnServer(key="currentActivityNum", value="-1")
		hub.device.updateStateOnServer(key="currentActivityName", value="PowerOff")
		self.triggerCheck(hub.device)

	def volumeMute(self, pluginAction):
		hubDevice = indigo.devices[pluginAction.deviceId]
		hub = self.hubDict[int(hubDevice.id)]
		soundDev = hub.activityList[hub.current_activity_id]["soundDev"]
		self.debugLog(hubDevice.name + u": sending Mute to " + soundDev)
		hub.client.send_command(soundDev, "Mute")
		
	def volumeDown(self, pluginAction):
		hubDevice = indigo.devices[pluginAction.deviceId]
		hub = self.hubDict[int(hubDevice.id)]
		soundDev = hub.activityList[hub.current_activity_id]["soundDev"]
		self.debugLog(hubDevice.name + u": sending VolumeDown to " + soundDev)
		hub.client.send_command(soundDev, "VolumeDown")
		
	def volumeUp(self, pluginAction):
		hubDevice = indigo.devices[pluginAction.deviceId]
		hub = self.hubDict[int(hubDevice.id)]
		soundDev = hub.activityList[hub.current_activity_id]["soundDev"]
		self.debugLog(hubDevice.name + u": sending VolumeUp to " + soundDev)
		hub.client.send_command(soundDev, "VolumeUp")

	def sendActivityCommand(self, pluginAction):
		hubDevice = indigo.devices[pluginAction.deviceId]
		client = self.hubDict[int(hubDevice.id)].client
		command = pluginAction.props["command"]
		activity = pluginAction.props["activity"]
		self.debugLog(hubDevice.name + u": sendActivityCommand: " + command + " to " + device)
		client.send_command(device, command)

	def sendDeviceCommand(self, pluginAction):
		hubDevice = indigo.devices[pluginAction.deviceId]
		client = self.hubDict[int(hubDevice.id)].client
		command = pluginAction.props["command"]
		device = pluginAction.props["device"]
		self.debugLog(hubDevice.name + u": sendDeviceCommand: " + command + " to " + device)
		client.send_command(device, command)

	def sendCommand(self, pluginAction):
		hubDevice = indigo.devices[pluginAction.deviceId]
		client = self.hubDict[int(hubDevice.id)].client
		command = pluginAction.props["command"]
		device = pluginAction.props["device"]
		self.debugLog(hubDevice.name + u": sendCommand: " + command + " to " + device)
		client.send_command(device, command)

	########################################
	# Menu Methods
	########################################

	def syncHub(self, valuesDict, typeId):
		self.debugLog(u"Syncing Hub")
		hubID = int(valuesDict['hubID'])
		client = self.hubDict[hubID].client
		client.sync()
		return (True, valuesDict)
		
	def dumpConfig(self, valuesDict, typeId):
		hubID = int(valuesDict['hubID'])
		config = self.hubDict[hubID].config
		self.debugLog(json.dumps(config, sort_keys=True, indent=4, separators=(',', ': ')))
		return (True, valuesDict)
		
	def parseConfig(self, valuesDict, typeId):
		hubID = int(valuesDict['hubID'])
		config = self.hubDict[hubID].config
		for activity in config["activity"]:
			if activity["id"] == "-1":		# skip Power Off
				continue
			self.debugLog(u"Activity: %s, id: %s, order: %i, type: %s, isAVActivity: %s, isTuningDefault: %s" % (activity['label'], activity['id'], activity['activityOrder'], activity['type'], str(activity['isAVActivity']), str(activity['isTuningDefault'])))
			for group in activity["controlGroup"]:
				self.debugLog(u"\tControl Group %s:" % group['name'])
				for function in group['function']:
					self.debugLog(u"\t\tFunction %s, label: %s, action %s:" % (function['name'], function['label'], function['action']))

		for device in config["device"]:
			self.debugLog(u"Device: %s, id: %s, type: %s, Manufacturer: %s, Model: %s" % (device['label'], device['id'], device['type'], device['manufacturer'], device['model']))
			for group in device["controlGroup"]:
				self.debugLog(u"\tControl Group %s:" % group['name'])
				for function in group['function']:
					self.debugLog(u"\t\tFunction %s, label: %s, action %s:" % (function['name'], function['label'], function['action']))

		return (True, valuesDict)
		
	def showActivity(self, valuesDict, typeId):
		hubID = int(valuesDict['hubID'])
		client = self.hubDict[hubID].client
		config = self.hubDict[hubID].config
		current_activity_id = client.get_current_activity()
		activity = [x for x in config['activity'] if x['id'] == current_activity_id][0]
		self.debugLog(json.dumps(activity, sort_keys=True, indent=4, separators=(',', ': ')))
		return (True, valuesDict)
		
	def checkForUpdates(self):
		self.updater.checkForUpdate()

	def updatePlugin(self):
		self.updater.update()

	def forceUpdate(self):
		self.updater.update(currentVersion='0.0.0')
			
	def toggleDebugging(self):
		if self.debug:
			self.debugLog(u"Turning off debug logging")
			self.pluginPrefs["showDebugInfo"] = False
		else:
			self.debugLog(u"Turning on debug logging")
			self.pluginPrefs["showDebugInfo"] = True
		self.debug = not self.debug

	########################################
	# ConfigUI methods
	########################################

	def activityListGenerator(self, filter, valuesDict, typeId, targetId):		
		hubID = int(targetId)
		retList = []
		for id,info in self.hubDict[hubID].activityList.iteritems():
			if id != -1:
				retList.append((id, info["label"]))
		retList.sort(key=lambda tup: tup[1])
		return retList
	
	def deviceListGenerator(self, filter, valuesDict, typeId, targetId):		
		retList = []			
		hubID = int(targetId)
		config = self.hubDict[hubID].config
		for device in config["device"]:
			retList.append((device['id'], device["label"]))
		retList.sort(key=lambda tup: tup[1])
		return retList

	def commandGroupListGenerator(self, filter, valuesDict, typeId, targetId):		
		retList = []
		if not valuesDict:
			return retList

		hubID = int(targetId)
		config = self.hubDict[hubID].config

		if typeId == "sendActivityCommand":
			for activity in config["activity"]:
				if activity["id"] != valuesDict['activity']:
					continue
				self.debugLog(u"commandGroupListGenerator Activity: %s, id: %s" % (activity['label'], activity['id']))
				for group in activity["controlGroup"]:
					retList.append((group['name'], group["name"]))

		elif typeId == "sendDeviceCommand":
			for device in config["device"]:
				if device["id"] != valuesDict['device']:
					continue
				self.debugLog(u"commandGroupListGenerator Device: %s, id: %s" % (device['label'], device['id']))
				for group in device["controlGroup"]:
					retList.append((group['name'], group["name"]))

		else:
			self.debugLog(u"commandGroupListGenerator Error: Unknown typeId (%s)" % typeId)
		
		retList.sort(key=lambda tup: tup[1])
		return retList
	
	def commandListGenerator(self, filter, valuesDict, typeId, targetId):		
		retList = []
		if not valuesDict:
			return retList

		hubID = int(targetId)
		config = self.hubDict[hubID].config

		if typeId == "sendActivityCommand":
			for activity in config["activity"]:
				if activity["id"] != valuesDict['activity']:
					continue
				self.debugLog(u"commandListGenerator Activity: %s, id: %s" % (activity['label'], activity['id']))
				for group in activity["controlGroup"]:
					if group["name"] != valuesDict['group']:
						continue
					for function in group['function']:
						retList.append((function['name'], function["label"]))	

		elif typeId == "sendDeviceCommand":
			for device in config["device"]:
				if device["id"] != valuesDict['device']:
					continue
				self.debugLog(u"commandListGenerator Device: %s, id: %s" % (device['label'], device['id']))
				for group in device["controlGroup"]:
					if group["name"] != valuesDict['group']:
						continue
					for function in group['function']:
						retList.append((function['name'], function["label"]))	

		else:
			self.debugLog(u"commandGroupListGenerator Error: Unknown typeId (%s)" % typeId)
		
		retList.sort(key=lambda tup: tup[1])
		return retList

	# doesn't do anything, just needed to force other menus to dynamically refresh
	
	def menuChanged(self, valuesDict, typeId, devId):
		return valuesDict

	def validateActionConfigUi(self, valuesDict, typeId, actionId):

		errorDict = indigo.Dict()

		if typeId == "startActivity":
			self.debugLog(u"validateActionConfigUi startActivity")
		
		elif typeId == "sendCommand":
			self.debugLog(u"validateActionConfigUi sendCommand")
			if valuesDict['device'] == "":
				errorDict["device"] = "Device must be entered"
			if valuesDict['command'] == "":
				errorDict["command"] = "Command must be entered"
		
		elif typeId == "setChannel":
			self.debugLog(u"validateActionConfigUi setChannel")
			if valuesDict['channel'] == "":
				errorDict["channel"] = "Channel must be entered"
			channel = int(valuesDict['channel'])
			if channel < 2 or channel > 120:
				errorDict["channel"] = "Channel out of range"
			return (True, valuesDict)
		
		elif typeId == "sendActivityCommand":
			self.debugLog(u"validateActionConfigUi sendActivityCommand")
			hubID = int(actionId)
			config = self.hubDict[hubID].config
			for activity in config["activity"]:
				if activity["id"] != valuesDict['activity']:
					continue
				for group in activity["controlGroup"]:
					if group["name"] != valuesDict['group']:
						continue
					for function in group['function']:
						if function['name'] != valuesDict['command']:
							continue
						action = json.loads(function["action"]) 
						valuesDict['device'] = action["deviceId"]						

			if valuesDict['activity'] == "":
				errorDict["activity"] = "Activity must be selected"
			if valuesDict['group'] == "":
				errorDict["group"] = "Command Group must be selected"
			if valuesDict['command'] == "":
				errorDict["command"] = "Command must be selected"
				
		elif typeId == "sendDeviceCommand":
			self.debugLog(u"validateActionConfigUi sendDeviceCommand")
			if valuesDict['device'] == "":
				errorDict["device"] = "Device must be selected"
			if valuesDict['group'] == "":
				errorDict["group"] = "Command Group must be selected"
			if valuesDict['command'] == "":
				errorDict["command"] = "Command must be selected"
				
		else:
			self.debugLog(u"validateActionConfigUi Error: Unknown typeId (%s)" % typeId)

		if len(errorDict) > 0:
			return (False, valuesDict, errorDict)
		else:
			return (True, valuesDict)
	

	def pickHub(self, filter=None, valuesDict=None, typeId=0, targetId=0):		
		retList =[]
		for id, hub in self.hubDict.items():
			retList.append((str(id),hub.device.name))
		retList.sort(key=lambda tup: tup[1])
		return retList
