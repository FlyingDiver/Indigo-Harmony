#!/usr/bin/env python2

"""Command line utility for querying the Logitech Harmony."""

import argparse
import logging
import sys

from harmony import auth
from harmony import client as harmony_client

LOGGER = logging.getLogger(__name__)

def login_to_logitech(args):
	"""Logs in to the Logitech service.

	Args:
	  args: argparse arguments needed to login.

	Returns:
	  Session token that can be used to log in to the Harmony device.
	"""
	token = auth.login(args.email, args.password)
	if not token:
		sys.exit('Could not get token from Logitech server.')

	session_token = auth.swap_auth_token(args.harmony_ip, args.harmony_port, token)
	if not session_token:
		sys.exit('Could not swap login token for session token.')

	return session_token

def pprint(obj):
	"""Pretty JSON dump of an object."""
	print(json.dumps(obj, sort_keys=True, indent=4, separators=(',', ': ')))

def get_client(args):
	"""Connect to the Harmony and return a Client instance."""
	token = login_to_logitech(args)
	client = harmony_client.create_and_connect_client(args.harmony_ip, args.harmony_port, token)
	return client

def show_config(args):
	"""Connects to the Harmony and prints its configuration."""
	client = get_client(args)
	config = client.get_config()
#	 pprint(client.get_config())	
	for activity in config["activity"]:
		print("Activity %s (%s), type %s" % (activity[u'label'], activity[u'id'], activity[u'type']))
#		pprint.pprint(activity)
	client.disconnect(send_close=True)
	return 0

def show_current_activity(args):
	"""Connects to the Harmony and prints the current activity block
	from the config."""
	client = get_client(args)
	config = client.get_config()
	current_activity_id = client.get_current_activity()

	activity = [x for x in config['activity'] if int(x['id']) == current_activity_id][0]

	pprint(activity)

	client.disconnect(send_close=True)
	return 0

def sync(args):
	"""Connects to the Harmony and syncs it.
	"""
	client = get_client(args)

	client.sync()

	client.disconnect(send_close=True)
	return 0


def turn_off(args):
	"""Sends a 'turn off' command to the harmony, which is the activity
	'-1'."""
	args.activity = '-1'
	start_activity(args)

def start_activity(args):
	"""Connects to the Harmony and switches to a different activity,
	specified as an id or label."""
	client = get_client(args)

	config = client.get_config()

	activity_off	 = False
	activity_numeric = False
	activity_id		 = None
	activity_label	 = None
	try:
		activity_off	 = float(args.activity) == -1
		activity_id		 = int(float(args.activity))
		activity_numeric = True
	except ValueError:
		activity_off   = args.activity.lower() == 'turn off'
		activity_label = str(args.activity)

	if activity_off:
		activity = [ {'id': -1, 'label': 'Turn Off'} ]
	else:
		activity = [x for x in config['activity']
			if (activity_numeric and int(x['id']) == activity_id)
				or x['label'].lower() == activity_label.lower()
		]

	if not activity:
		LOGGER.error('could not find activity: ' + args.activity)
		client.disconnect(send_close=True)
		return 1

	activity = activity[0]

	client.start_activity(int(activity['id']))

	LOGGER.info("started activity: '%s' of id: '%s'" % (activity['label'], activity['id']))

	client.disconnect(send_close=True)
	return 0

def send_command(args):
	"""Connects to the Harmony and send a simple command."""
	client = get_client(args)

	config = client.get_config()

	device = args.device if args.device_id is None else args.device_id

	device_numeric = None
	try:
		device_numeric = int(float(device))
	except ValueError:
		pass

	device_config = [x for x in config['device'] if device.lower() == x['label'].lower() or
				  ((device_numeric is not None) and device_numeric == int(x['id']))]

	if not device_config:
		LOGGER.error('could not find device: ' + device)
		client.disconnect(send_close=True)
		return 1

	device_id = int(device_config[0]['id'])

	client.send_command(device_id, args.command)

	client.disconnect(send_close=True)
	return 0


def main():
	"""Main method for the script."""
	parser = argparse.ArgumentParser(description='pyharmony utility script',formatter_class=argparse.ArgumentDefaultsHelpFormatter)

	# Required flags go here.
	required_flags = parser.add_argument_group('required arguments')
	required_flags.add_argument('--email', required=True, help=('Logitech username in the form of an email address.'))
	required_flags.add_argument('--password', required=True, help='Logitech password.')
	required_flags.add_argument('--harmony_ip', required=True, help='IP Address of the Harmony device.')

	# Flags with defaults go here.
	parser.add_argument('--harmony_port', default=5222, type=int, help=('Network port that the Harmony is listening on.'))
	loglevels = dict((logging.getLevelName(level), level)
					 for level in [10, 20, 30, 40, 50])
	parser.add_argument('--loglevel', default='INFO', choices=loglevels.keys(), help='Logging level to print to the console.')

	subparsers = parser.add_subparsers()
	
	show_config_parser = subparsers.add_parser('show_config', help='Print the Harmony device configuration.')
	show_config_parser.set_defaults(func=show_config)
	
	show_activity_parser = subparsers.add_parser('show_current_activity', help='Print the current activity config.')
	show_activity_parser.set_defaults(func=show_current_activity)

	start_activity_parser = subparsers.add_parser('start_activity', help='Switch to a different activity.')
	start_activity_parser.add_argument('activity', help='Activity to switch to, id or label.')
	start_activity_parser.set_defaults(func=start_activity)

	sync_parser = subparsers.add_parser('sync', help='Sync the harmony.')
	sync_parser.set_defaults(func=sync)

	turn_off_parser = subparsers.add_parser('turn_off', help='Send a turn off command to the harmony.')
	turn_off_parser.set_defaults(func=turn_off)

	command_parser = subparsers.add_parser('send_command', help='Send a simple command.')
	command_parser.add_argument('--command', help='IR Command to send to the device.', required=True)
	device_arg_group = command_parser.add_mutually_exclusive_group(required=True)
	device_arg_group.add_argument('--device_id', help='Specify the device id to which we will send the command.')
	device_arg_group.add_argument('--device', help='Specify the device id or label to which we will send the command.')
	
	command_parser.set_defaults(func=send_command)

	args = parser.parse_args()

	logging.basicConfig(level=loglevels[args.loglevel], format='%(levelname)s\t%(name)s\t%(message)s')

	sys.exit(args.func(args))

if __name__ == '__main__':
	main()
