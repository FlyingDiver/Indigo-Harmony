"""Client class for connecting to the Logitech Harmony."""

import json
import logging
import time

import sleekxmpp
from sleekxmpp.xmlstream import ET

LOGGER = logging.getLogger(__name__)

from sleekxmpp.xmlstream.matcher.base import MatcherBase
from sleekxmpp.xmlstream.handler import Callback

import indigo

class MatchAll(MatcherBase):
	def __init__(self, criteria):
		self._criteria = criteria

	def match(self, xml):
		"""Check if a stanza matches the stored criteria.
		Meant to be overridden.
		"""
		return True

class MatchNone(MatcherBase):
	def __init__(self, criteria):
		self._criteria = criteria

	def match(self, xml):
		"""Check if a stanza matches the stored criteria.
		Meant to be overridden.
		"""
		return False

class MatchMessage(MatcherBase):
	def __init__(self, criteria):
		self._criteria = criteria

	def match(self, xml):
	
		if type(xml) == sleekxmpp.stanza.stream_features.StreamFeatures:
#			indigo.server.log(u"MatchMessage: sleekxmpp.stanza.stream_features.StreamFeatures")
			pass
		elif type(xml) == sleekxmpp.features.feature_mechanisms.stanza.success.Success:
#			indigo.server.log(u"MatchMessage: sleekxmpp.features.feature_mechanisms.stanza.success.Success")
			pass
		elif type(xml) == sleekxmpp.stanza.iq.Iq:
#			indigo.server.log(u"MatchMessage: sleekxmpp.stanza.iq.Iq %s" % xml['type'])
			pass
		elif type(xml) == sleekxmpp.stanza.message.Message:
#			indigo.server.log(u"MatchMessage: sleekxmpp.stanza.message.Message, xml = \n%s\n" % (repr(xml)))
			root = ET.fromstring(str(xml))
			indigo.server.log(u"MatchMessage: sleekxmpp.stanza.message.Message, root = %s, %s, %s" % (root.tag, root.attrib, root.text))
			for child in root:
				indigo.server.log(u"MatchMessage: sleekxmpp.stanza.message.Message, child = %s, attrib = %s\n%s " % (child.tag, child.attrib, child.text))
#			indigo.server.log(u"MatchMessage: sleekxmpp.stanza.message.Message, tag = %s, text = %s" % (root[0][1].tag, root[0][1].text))
		else:
			indigo.server.log(u"MatchMessage: %s" % type(xml))
		
		return False

class HarmonyClient(sleekxmpp.ClientXMPP):
	"""An XMPP client for connecting to the Logitech Harmony."""

	def __init__(self, auth_token, message_callback=None):
		user = '%s@connect.logitech.com/gatorade.' % auth_token
		password = auth_token
		plugin_config = {
			# Enables PLAIN authentication which is off by default.
			'feature_mechanisms': {'unencrypted_plain': True},
		}
		super(HarmonyClient, self).__init__(user, password, plugin_config=plugin_config)
		self.registerHandler(Callback('Example Handler', MatchMessage(''), message_callback))

	def get_config(self):
		"""Retrieves the Harmony device configuration.

		Returns:
		  A nested dictionary containing activities, devices, etc.
		"""
		iq_cmd = self.Iq()
		iq_cmd['type'] = 'get'
		action_cmd = ET.Element('oa')
		action_cmd.attrib['xmlns'] = 'connect.logitech.com'
		action_cmd.attrib['mime'] = (
			'vnd.logitech.harmony/vnd.logitech.harmony.engine?config')
		iq_cmd.set_payload(action_cmd)
		result = iq_cmd.send(block=True)
		payload = result.get_payload()
		assert len(payload) == 1
		action_cmd = payload[0]
		assert action_cmd.attrib['errorcode'] == '200'
		device_list = action_cmd.text
		return json.loads(device_list)

	def get_current_activity(self):
		"""Retrieves the current activity.

		Returns:
		  A int with the activity ID.
		"""
		iq_cmd = self.Iq()
		iq_cmd['type'] = 'get'
		action_cmd = ET.Element('oa')
		action_cmd.attrib['xmlns'] = 'connect.logitech.com'
		action_cmd.attrib['mime'] = (
			'vnd.logitech.harmony/vnd.logitech.harmony.engine?getCurrentActivity')
		iq_cmd.set_payload(action_cmd)
		result = iq_cmd.send(block=True)
		payload = result.get_payload()
		assert len(payload) == 1
		action_cmd = payload[0]
		assert action_cmd.attrib['errorcode'] == '200'
		activity = action_cmd.text.split("=")
		return int(activity[1])

	def _timestamp(self):
		return str(int(round(time.time() * 1000)))

	def start_activity(self, activity_id):
		"""Starts an activity.

		Args:
			activity_id: An int or string identifying the activity to start

		Returns:
		  A nested dictionary containing activities, devices, etc.
		"""
		iq_cmd = self.Iq()
		iq_cmd['type'] = 'get'
		action_cmd = ET.Element('oa')
		action_cmd.attrib['xmlns'] = 'connect.logitech.com'
		action_cmd.attrib['mime'] = ('harmony.activityengine?runactivity')
		cmd = 'activityId=' + str(activity_id) + ':timestamp=' + self._timestamp() + ':async=1'
		action_cmd.text = cmd
		iq_cmd.set_payload(action_cmd)
		iq_cmd.send(block=True)
		return True

	def sync(self):
		"""Syncs the harmony hub with the web service.
		"""
		iq_cmd = self.Iq()
		iq_cmd['type'] = 'get'
		action_cmd = ET.Element('oa')
		action_cmd.attrib['xmlns'] = 'connect.logitech.com'
		action_cmd.attrib['mime'] = ('setup.sync')
		iq_cmd.set_payload(action_cmd)
		result = iq_cmd.send(block=True)
		payload = result.get_payload()
		assert len(payload) == 1

	def send_command(self, device_id, command):
		"""Send a simple command to the Harmony Hub.
		"""
		iq_cmd = self.Iq()
		iq_cmd['type'] = 'get'
		iq_cmd['id'] = '5e518d07-bcc2-4634-ba3d-c20f338d8927-2'
		action_cmd = ET.Element('oa')
		action_cmd.attrib['xmlns'] = 'connect.logitech.com'
		action_cmd.attrib['mime'] = (
			'vnd.logitech.harmony/vnd.logitech.harmony.engine?holdAction')
		action_cmd.text = 'action={"type"::"IRCommand","deviceId"::"'+str(device_id)+'","command"::"'+command+'"}:status=press'
		iq_cmd.set_payload(action_cmd)
		result = iq_cmd.send(block=False)
		# FIXME: This is an ugly hack, we need to follow the actual
		# protocol for sending a command, since block=True does not
		# work.
		time.sleep(0.5)
		return True

	def change_channel(self, channel):
		"""Changes a channel.
		Args:
			channel: Channel number
		Returns:
		  An HTTP 200 response (hopefully)
		"""
		iq_cmd = self.Iq()
		iq_cmd['type'] = 'get'
		action_cmd = ET.Element('oa')
		action_cmd.attrib['xmlns'] = 'connect.logitech.com'
		action_cmd.attrib['mime'] = ('harmony.engine?changeChannel')
		cmd = 'channel=' + str(channel) + ':timestamp=0'
		action_cmd.text = cmd
		iq_cmd.set_payload(action_cmd)
		result = iq_cmd.send(block=True)
		payload = result.get_payload()
		assert len(payload) == 1
		action_cmd = payload[0]
		return action_cmd.text

	def turn_off(self):
		"""Turns the system off if it's on, otherwise it does nothing.

		Returns:
		  True.
		"""
		activity = self.get_current_activity()
		print activity
		if activity != -1:
			print "OFF"
			self.start_activity(-1)
		return True

def create_and_connect_client(ip_address, port, token, message_callback=None):
	"""Creates a Harmony client and initializes session.

	Args:
	  ip_address: IP Address of the Harmony device.
	  port: Port that the Harmony device is listening on.
	  token: A string containing a session token.

	Returns:
	  An instance of HarmonyClient that is connected.
	"""
	client = HarmonyClient(token, message_callback)
	client.connect(address=(ip_address, port),
				   use_tls=False, use_ssl=False)
	client.process(block=False)

	while not client.sessionstarted:
		time.sleep(0.1)

	return client
