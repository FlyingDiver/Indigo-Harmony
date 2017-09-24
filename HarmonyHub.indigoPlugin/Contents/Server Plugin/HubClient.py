import logging
import time
import json
import socket

import sleekxmpp
from sleekxmpp.xmlstream import ET
from sleekxmpp.xmlstream.matcher.base import MatcherBase
from sleekxmpp.xmlstream.handler import Callback

from pyharmony import auth as harmony_auth
from pyharmony import client as harmony_client

import indigo

class MatchMessage(MatcherBase):
    def __init__(self, criteria):
        self._criteria = criteria
        self.logger = logging.getLogger("Plugin.MatchMessage")

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
            self.logger.info(u"match: unknown xml type: %s" % type(xml))
            return False

class HubClient(object):

    def __init__(self, plugin, device):
        self.plugin = plugin
        self.deviceId = device.id
        self.logger = logging.getLogger("Plugin.HubClient")

        self.ready = False

        self.harmony_ip = device.pluginProps['address']
        self.harmony_port = 5222

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        try:
            s.connect((self.harmony_ip, self.harmony_port))
            s.shutdown(2)
            self.logger.debug(device.name + u": Socket test OK")
        except:
            self.logger.warning(device.name + u": Socket test failure")
            return
 
        try:
            self.auth_token = harmony_auth.get_auth_token(self.harmony_ip, self.harmony_port)
            if not self.auth_token:
                self.logger.warning(device.name + u': harmony_auth.get_auth_token failure')

            self.client = harmony_client.HarmonyClient(self.auth_token)
            self.client.registerHandler(Callback('Hub Message Handler', MatchMessage(''), self.messageHandler))

            if not self.client.connect(address=(self.harmony_ip, self.harmony_port), use_tls=False, use_ssl=False):
                raise Exception("connect failure on HarmonyClient")

            self.client.process(block=False)
            while not self.client.sessionstarted:
                self.logger.debug(device.name + u": Waiting for client.sessionstarted")
                time.sleep(0.1)

            self.refreshConfig(device)
            self.ready = True

        except Exception as e:
            self.logger.debug(device.name + u": Error setting up hub connection: " + str(e))



    def refreshConfig(self, device):

        try:
            self.config = self.client.get_config()
        except sleekxmpp.exceptions.IqTimeout:
            self.logger.debug(device.name + u": Time out in client.get_config")
            return
        except sleekxmpp.exceptions.IqError:
            self.logger.debug(device.name + u": IqError in client.get_config")
            return

        try:
            self.current_activity_id = str(self.client.get_current_activity())
        except sleekxmpp.exceptions.IqTimeout:
            self.logger.debug(device.name + u": Time out in client.get_current_activity")
            self.current_activity_id = "0"
        except sleekxmpp.exceptions.IqError:
            self.logger.debug(device.name + u": IqError in client.get_current_activity")
            self.current_activity_id = "0"
        else:
            for activity in self.config["activity"]:
                if activity[u'id'] == self.current_activity_id:
                    self.logger.debug(device.name + u": Activity: %s (%s) - Current Activity" % (activity[u'label'], activity[u'id']))
                    stateList = [   {'key':'currentActivityNum', 'value':activity[u'id']},
                                    {'key':'currentActivityName', 'value':activity[u'label']}   ]
                    device.updateStatesOnServer(stateList)
                else:
                    self.logger.debug(device.name + u": Activity: %s (%s)" % (activity[u'label'], activity[u'id']))


    def messageHandler(self, data):
        hubDevice = indigo.devices[self.deviceId]

        root = ET.fromstring(str(data))
        for child in root:
            if "event" in child.tag:
                if "notify" in str(child.attrib):
                    if "connect.stateDigest" in str(child.attrib):
                        try:
                            self.logger.threaddebug(hubDevice.name + u": messageHandler: Event connect.stateDigest, child.text = %s" % (child.text))
                            content = json.loads(child.text)
                        except Exception as e:
                            self.logger.error(hubDevice.name + u": Event state notify child.text parse error = %s" % str(e))
                            self.logger.error(hubDevice.name + u": Event state notify child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
                        else:
                            self.logger.debug(hubDevice.name + u": messageHandler: Event state notify, activityId = %s, activityStatus = %s" % (content['activityId'], content['activityStatus']))
                            stateList = [   {'key':'notifyActivityId', 'value':content['activityId']},
                                            {'key':'notifyActivityStatus', 'value':content['activityStatus']}
                                        ]
                            hubDevice.updateStatesOnServer(stateList)
                            broadcastDict = {'notifyActivityId': content['activityId'], 'notifyActivityStatus': content['activityStatus']}
                            indigo.server.broadcastToSubscribers(u"activityNotification", broadcastDict)
                            self.plugin.triggerCheck(hubDevice, "activityNotification")

                    elif "automation.state" in str(child.attrib):
                        try:
                            self.logger.threaddebug(hubDevice.name + u": messageHandler: Event automation.state, child.text = %s" % (child.text))
                            content = json.loads(child.text)
                        except Exception as e:
                            self.logger.error(hubDevice.name + u": Event automation notify child.text parse error = %s" % str(e))
                            self.logger.error(hubDevice.name + u": Event automation notify child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
                        else:
                            self.logger.debug(hubDevice.name + u": messageHandler: Event automation notify, contents:")
                            for key, device in content.items():
                                self.logger.debug(hubDevice.name + u": Device: %s, status: %s, brightness: %i, on: %r" % (key, device['status'], device['brightness'], device['on']))
                                stateList = [   {'key':'lastAutomationDevice', 'value':key},
                                                {'key':'lastAutomationStatus', 'value':device['status']},
                                                {'key':'lastAutomationBrightness', 'value':str(device['brightness'])},
                                                {'key':'lastAutomationOnState', 'value':str(device['on'])}
                                            ]
                                hubDevice.updateStatesOnServer(stateList)
                                broadcastDict = {'lastAutomationDevice': key, 'lastAutomationStatus': device['status'], 'lastAutomationBrightness': device['brightness'], 'lastAutomationOnState': device['on']}
                                indigo.server.broadcastToSubscribers(u"automationNotification", broadcastDict)
                                self.plugin.triggerCheck(hubDevice, "automationNotification")

                    elif "harmonyengine.metadata" in str(child.attrib):
                        self.logger.threaddebug(hubDevice.name + u": messageHandler: Event harmonyengine.metadata, child.text = %s" % (child.text))
                        hubDevice.updateStateOnServer(key='lastMetadataUpdate', value=child.text)
                        self.plugin.triggerCheck(hubDevice, "metadataNotification")
                        
                    else:
                        self.logger.error(hubDevice.name + u": messageHandler: Unknown Event Type: %s\n%s" % (child.attrib, child.text))

                elif "startActivityFinished" in str(child.attrib):
                    try:
                        self.logger.threaddebug(hubDevice.name + u": messageHandler: Event startActivityFinished, child.text = %s" % (child.text))
                        pairs = child.text.split(':')
#                        self.logger.debug(hubDevice.name + u": messageHandler: Event startActivityFinished, pairs = %s" % (str(pairs)))
                        for item in pairs:
#                            self.logger.debug(hubDevice.name + u": messageHandler: Event startActivityFinished, item = %s" % (str(item)))
                            temp = item.split('=')
                            if temp[0] == 'errorCode':
                                errorCode = temp[1]
                            elif temp[0] == 'errorString':
                                errorString =  temp[1]
                            elif temp[0] == 'activityId':
                                activityId =  temp[1]
                            else:
                                self.logger.debug(hubDevice.name + u": messageHandler: Event startActivityFinished, unknown key/value: %s" % (item))
                                  
                    except Exception as e:
                        self.logger.error(hubDevice.name + u": Event startActivityFinished child.text parse error = %s" % str(e))
                        self.logger.error(hubDevice.name + u": Event startActivityFinished child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
                    else:
                        self.logger.debug(hubDevice.name + u": messageHandler: Event startActivityFinished, activityId = %s, errorCode = %s, errorString = %s" % (activityId, errorCode, errorString))
                        for activity in self.config["activity"]:
                            if activityId == activity[u'id']:
                                stateList = [   {'key':'currentActivityNum', 'value':activity[u'id']},
                                                {'key':'currentActivityName', 'value':activity[u'label']}
                                            ]
                                hubDevice.updateStatesOnServer(stateList)
                                broadcastDict = {'currentActivityNum': activity[u'id'], 'currentActivityName': activity[u'label']}
                                indigo.server.broadcastToSubscribers(u"activityFinishedNotification", broadcastDict)
                                break
                        self.plugin.triggerCheck(hubDevice, "activityFinishedNotification")

                elif "pressType" in str(child.attrib):
                    pass
                    
#                     try:
#                         self.logger.threaddebug(hubDevice.name + u": messageHandler: Event pressType, child.text = %s" % (child.text))
#                         pressType = child.text.split('=')
#                         self.logger.debug(hubDevice.name + u": messageHandler: Event pressType, Type = %s" % pressType[1])
#                     except Exception as e:
#                         self.logger.error(hubDevice.name + u": Event pressType child.text parse error = %s" % str(e))
#                         self.logger.error(hubDevice.name + u": Event pressType child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
#                     self.plugin.triggerCheck(hubDevice, "pressTypeNotification")

                elif "startActivity" in str(child.attrib):
                    try:
                        self.logger.threaddebug(hubDevice.name + u": messageHandler: Event startActivity, child.text = %s" % (child.text))
                        pairs = child.text.split(':')
                        for item in pairs:
#                            self.logger.debug(hubDevice.name + u": messageHandler: Event startActivity, item = %s" % (str(item)))
                            temp = item.split('=')
                            if temp[0] == 'done':
                                done = temp[1]
                            elif temp[0] == 'total':
                                total =  temp[1]
                            elif temp[0] == 'deviceId':
                                deviceId =  temp[1]
                            else:
                                self.logger.debug(hubDevice.name + u": messageHandler: Event startActivity, unknown key/value: %s" % (item))

                    except Exception as e:
                        self.logger.error(hubDevice.name + u": Event startActivity child.text parse error = %s" % str(e))
                        self.logger.error(hubDevice.name + u": Event startActivity child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
                    else:
                        self.logger.debug(hubDevice.name + u": messageHandler: Event startActivity, done = %s, total = %s, deviceId = %s" % (done, total, deviceId))
                        self.plugin.triggerCheck(hubDevice, "startActivityNotification")

                elif "helpdiscretes" in str(child.attrib):
                    pass
                
#                     try:
#                         self.logger.threaddebug(hubDevice.name + u": messageHandler: Event helpdiscretes, child.text = %s" % (child.text))
#                         pairs = child.text.split(':')
#                         for item in pairs:
#                             self.logger.debug(hubDevice.name + u": messageHandler: Event helpdiscretes, item = %s" % (str(item)))
#                             temp = item.split('=')
#                             if temp[0] == 'done':
#                                 done = temp[1]
#                             elif temp[0] == 'total':
#                                 total =  temp[1]
#                             elif temp[0] == 'deviceId':
#                                 deviceId =  temp[1]
#                             else:
#                                 self.logger.debug(hubDevice.name + u": messageHandler: Event helpdiscretes, unknown key/value: %s" % (item))
# 
#                     except Exception as e:
#                         self.logger.error(hubDevice.name + u": Event helpdiscretes child.text parse error = %s" % str(e))
#                         self.logger.error(hubDevice.name + u": Event helpdiscretes child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
#                     else:
#                         if len(pairs) > 1:
#                             self.logger.debug(hubDevice.name + u": messageHandler: Event helpdiscretes, done = %s, total = %s, deviceId = %s, isHelpDiscretes = %s" % (done[1], total[1], deviceId[1], isHelpDiscretes[1]))
#                         else:
#                             self.logger.debug(hubDevice.name + u": messageHandler: Event helpdiscretes, deviceId = %s" % deviceId[1])
#                         self.plugin.triggerCheck(hubDevice, "helpdiscretesNotification")

                else:
                    self.logger.error(hubDevice.name + u": messageHandler: Unknown Event Type: %s\n%s" % (child.attrib, child.text))

            else:
                self.logger.error(hubDevice.name + u": messageHandler: Unknown Message Type: " + child.tag)


