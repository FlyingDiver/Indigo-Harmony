import logging
import time
import json

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

        self.harmony_ip = device.pluginProps['address']
        self.harmony_port = 5222

        self.ready = False

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
                        self.logger.debug(hubDevice.name + u": messageHandler: Event automation notify, contents:")
                        try:
                            content = json.loads(child.text)
                        except Exception as e:
                            self.logger.error(hubDevice.name + u": Event automation notify child.text parse error = %s" % str(e))
                            self.logger.error(hubDevice.name + u": Event automation notify child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
                        else:
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
                    else:
                        self.logger.error(hubDevice.name + u": messageHandler: Unknown Event Type: %s\n%s" % (child.attrib, child.text))

                elif "startActivityFinished" in str(child.attrib):
                    try:
                        pairs = child.text.split(':')
                        activityId = pairs[0].split('=')
                        errorCode = pairs[1].split('=')
                        errorString = pairs[2].split('=')
                    except Exception as e:
                        self.logger.error(hubDevice.name + u": Event startActivityFinished child.text parse error = %s" % str(e))
                        self.logger.error(hubDevice.name + u": Event startActivityFinished child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
                    else:
                        self.logger.debug(hubDevice.name + u": messageHandler: Event startActivityFinished, activityId = %s, errorCode = %s, errorString = %s" % (activityId[1], errorCode[1], errorString[1]))
                        for activity in self.config["activity"]:
                            if activityId[1] == activity[u'id']:
                                stateList = [   {'key':'currentActivityNum', 'value':activity[u'id']},
                                                {'key':'currentActivityName', 'value':activity[u'label']}
                                            ]
                                hubDevice.updateStatesOnServer(stateList)
                                broadcastDict = {'currentActivityNum': activity[u'id'], 'currentActivityName': activity[u'label']}
                                indigo.server.broadcastToSubscribers(u"activityFinishedNotification", broadcastDict)
                                self.plugin.triggerCheck(hubDevice, "activityFinishedNotification")
                                break

                elif "pressType" in str(child.attrib):
                    try:
                        pressType = child.text.split('=')
                        self.logger.debug(hubDevice.name + u": messageHandler: Event pressType, Type = %s" % pressType[1])
                    except Exception as e:
                        self.logger.error(hubDevice.name + u": Event pressType child.text parse error = %s" % str(e))
                        self.logger.error(hubDevice.name + u": Event pressType child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))

                elif "startActivity" in str(child.attrib):
                    try:
                        pairs = child.text.split(':')
                        done = pairs[0].split('=')
                        total = pairs[1].split('=')
                        deviceId = pairs[2].split('=')
                    except Exception as e:
                        self.logger.error(hubDevice.name + u": Event startActivity child.text parse error = %s" % str(e))
                        self.logger.error(hubDevice.name + u": Event startActivity child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
                    else:
                        self.logger.debug(hubDevice.name + u": messageHandler: Event startActivity, done = %s, total = %s, deviceId = %s" % (done[1], total[1], deviceId[1]))

                elif "helpdiscretes" in str(child.attrib):
                    try:
                        pairs = child.text.split(':')
                        if len(pairs) > 1:
                            done = pairs[0].split('=')
                            total = pairs[1].split('=')
                            deviceId = pairs[2].split('=')
                            isHelpDiscretes = pairs[2].split('=')
                        else:
                            deviceId = pairs[0].split('=')

                    except Exception as e:
                        self.logger.error(hubDevice.name + u": Event startActivity child.text parse error = %s" % str(e))
                        self.logger.error(hubDevice.name + u": Event startActivity child.attrib = %s, child.text:\n%s" % (child.attrib, child.text))
                    else:
                        if len(pairs) > 1:
                            self.logger.debug(hubDevice.name + u": messageHandler: Event helpdiscretes, done = %s, total = %s, deviceId = %s, isHelpDiscretes = %s" % (done[1], total[1], deviceId[1], isHelpDiscretes[1]))
                        else:
                            self.logger.debug(hubDevice.name + u": messageHandler: Event helpdiscretes, deviceId = %s" % deviceId[1])

                else:
                    self.logger.error(hubDevice.name + u": messageHandler: Unknown Event Type: %s\n%s" % (child.attrib, child.text))

            else:
                self.logger.error(hubDevice.name + u": messageHandler: Unknown Message Type: " + child.tag)

