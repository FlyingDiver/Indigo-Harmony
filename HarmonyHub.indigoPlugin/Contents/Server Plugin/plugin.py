#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import json
import sleekxmpp
from sleekxmpp.xmlstream import ET


from ghpu import GitHubPluginUpdater
from harmony import auth
from harmony import client as harmony_client

kCurDevVersCount = 0		# current version of plugin devices

class HubClient(object):

	def __init__(self, plugin, device):
		self.plugin = plugin
		self.device = device
		
		self.harmony_ip = device.pluginProps['address']
		self.harmony_port = 5222
	
		self.auth_token = auth.login(device.pluginProps['harmonyLogin'], device.pluginProps['harmonyPassword'])
		if not self.auth_token:
			self.plugin.debugLog(device.name + u': Could not get token from Logitech server.')

		self.session_token = auth.swap_auth_token(self.harmony_ip, self.harmony_port, self.auth_token)
		if not self.session_token:
			self.plugin.debugLog(device.name + u': Could not swap login token for session token.')

		self.client = harmony_client.create_and_connect_client(self.harmony_ip, self.harmony_port, self.session_token)

		self.client.add_event_handler("session_start", self.session_start)
#		self.client.add_event_handler("stanza", self.stanza)
#		self.client.add_event_handler("message", self.message)

#		self.client.process(block=False)
	
		self.activityList = dict()
		self.config = self.client.get_config()
		self.current_activity_id = self.client.get_current_activity()
		for activity in self.config["activity"]:
			self.activityList[activity[u'id']] = {'label': activity[u'label'], 'type': activity[u'type'] }
			if self.current_activity_id == int(activity[u'id']):
				self.device.updateStateOnServer(key="activityNum", value=activity[u'id'])
				self.device.updateStateOnServer(key="activityName", value=activity[u'label'])
				self.plugin.debugLog(device.name + u": Activity: " + activity[u'label'] + '  *Active*')
			else:
				self.plugin.debugLog(device.name + u": Activity: " + activity[u'label'])

	def session_start(self, data):
		self.plugin.debugLog(self.device.name + u": session_start, data = " + str(event))
#		self.client.send_presence()
#		self.client.get_roster()
#		self.client.process(block=False)
	
#	def stanza(self, data):
#		self.plugin.debugLog(self.device.name + u": stanza, data = " + str(stanza))
#		self.client.process(block=False)
	
#	def message(self, data):
#		self.plugin.debugLog(self.device.name + u": message, data = " + str(msg))
#		self.client.process(block=False)
	
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
		self.next_update_check = time.time() + float(self.pluginPrefs.get('updateFrequency', 24)) * 60.0 * 60.0

		self.hubDict = dict()
		self.triggers = { }
		
		# Need to subscribe to device changes here so we can call the refreshDeviceList method
		# in case there was a change or deletion of a device that's published
		indigo.devices.subscribeToChanges()

		# set up the XMPP client here
		
		
							
	def shutdown(self):
		indigo.server.log(u"Shutting down Harmony Hub")

		# close the XMPP client here


	def runConcurrentThread(self):

		try:
			while True:
			
				# for now, poll the hubs for activity changes
				
				for id, hub in self.hubDict.items():
					self.debugLog(hub.device.name + u": checking current activity")
					hub.current_activity_id = hub.client.get_current_activity()
					for activity in hub.config["activity"]:
						if hub.current_activity_id == int(activity[u'id']):
							hub.device.updateStateOnServer(key="activityNum", value=activity[u'id'])
							hub.device.updateStateOnServer(key="activityName", value=activity[u'label'])
							break
						

				# Plugin Update check
				
				if time.time() > self.next_update_check:
					self.updater.checkForUpdate()
					self.next_update_check = time.time() + float(self.pluginPrefs['updateFrequency']) * 60.0 * 60.0

				self.sleep(60.0)	
								
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
		self.debugLog("Adding Trigger %s (%d)" % (trigger.name, trigger.id))
		assert trigger.id not in self.triggers
		self.triggers[trigger.id] = trigger
 
	def triggerStopProcessing(self, trigger):
		self.debugLog("Removing Trigger %s (%d)" % (trigger.name, trigger.id))
		assert trigger.id in self.triggers
		del self.triggers[trigger.id] 

	def triggerCheck(self, device):
		self.debugLog("Checking Triggers for Device %s (%d)" % (device.name, device.id))
	
			
	
	####################
	def validatePrefsConfigUi(self, valuesDict):
		self.debugLog(u"validatePrefsConfigUi called")
		errorMsgDict = indigo.Dict()
		try:
			poll = int(valuesDict['updateFrequency'])
			if (poll <= 0) or (poll > 24):
				raise
		except:
			errorMsgDict['updateFrequency'] = u"Update frequency is invalid - enter a valid number (between 1 and 24)"
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
						
		instanceVers = int(device.pluginProps.get('devVersCount', 0))
		self.debugLog(device.name + u": Device Current Version = " + str(instanceVers))

		if instanceVers >= kCurDevVersCount:
			self.debugLog(device.name + u": Device Version is up to date")
			
		elif instanceVers < kCurDevVersCount:
			newProps = device.pluginProps

		else:
			self.errorLog(u"Unknown device version: " + str(instanceVers) + " for device " + device.name)					
			
		if len(device.pluginProps) < 3:
			self.errorLog(u"Server \"%s\" is misconfigured - disabling" % device.name)
			indigo.device.enable(device, value=False)
				
		else:			
			if int(device.id) not in self.hubDict:
				if device.deviceTypeId == "harmonyHub":
					self.debugLog(device.name + u": Starting harmonyHub device")
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
	# Plugin Actions object callbacks (pluginAction is an Indigo plugin action instance)
	######################

	def startActivity(self, pluginAction):
		hubDevice = indigo.devices[pluginAction.deviceId]
		hub = self.hubDict[int(hubDevice.id)]
		activityID = pluginAction.props["activity"]
		activityLabel = hub.activityList[activityID]["label"]
		hubDevice.updateStateOnServer(key="activityNum", value=activityID)
		hubDevice.updateStateOnServer(key="activityName", value=activityLabel)
		self.debugLog(hubDevice.name + u": Start Activity - " + activityLabel)
		hub.client.start_activity(int(activityID))


	def powerOff(self, pluginAction):
		hubDevice = indigo.devices[pluginAction.deviceId]
		client = self.hubDict[int(hubDevice.id)].client

		self.debugLog(hubDevice.name + u": Power Off")
		client.start_activity(-1)

	def setChannel(self, pluginAction):
		hubDevice = indigo.devices[pluginAction.deviceId]
		client = self.hubDict[int(hubDevice.id)].client
		channel = pluginAction.props["channel"]
		if '.' not in channel:
			channel = channel + ".1"
		self.debugLog(hubDevice.name + u": Change Channel to " + channel)
		client.change_channel(channel)

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
		client = self.hubDict[hubID].client
		config = client.get_config()
		self.debugLog(json.dumps(config, sort_keys=True, indent=4, separators=(',', ': ')))
		return (True, valuesDict)
		
	def showActivity(self, valuesDict, typeId):
		hubID = int(valuesDict['hubID'])
		client = self.hubDict[hubID].client
		config = client.get_config()
		current_activity_id = client.get_current_activity()
		activity = [x for x in config['activity'] if int(x['id']) == current_activity_id][0]
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

	def pickHub(self, filter=None, valuesDict=None, typeId=0, targetId=0):		
		retList =[]
		for id, hub in self.hubDict.items():
			retList.append((str(id),hub.device.name))
		retList.sort(key=lambda tup: tup[1])
		return retList
