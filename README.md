# Harmony Hub

Plugin for the Indigo Home Automation system.

This plugin enables monitoring of certain activities on the Harmony Hub, and provides the capability to send Activity changes and device commands to the Hub.

| Requirement            |            |
|------------------------|------------|
| Minimum Indigo Version | 2022.1     |
| Python Library (API)   | Unofficial |
| Requires Local Network | Yes        |
| Requires Internet      | No         |
| Hardware Interface     | None       |


## Installation Instructions

This plugin uses compiled Python3 libraries.  You must have Xcode installed to install these libraries.

In Terminal.app enter:

`pip3 install aioharmony`

The plugin can use either WebSockets or XMPP for communication with the Hubs.  The default is WebSockets, but can be changed in the plugin Preferences dialog.  See https://support.logi.com/hc/en-001/community/posts/360032837213-Update-to-accessing-Harmony-Hub-s-local-API-via-XMPP 
for instructions.


### Broadcast Messages

    MessageType: activityNotification 
    Returns dictionary:
    {
    	'notifyActivityId':			<text string>,
		'notifyActivityStatus':		<text string>
	}

    MessageType: activityFinishedNotification
    Returns dictionary:
    {
    	'currentActivityNum':  		<text string>,
		'currentActivityName': 		<text string>
	}

    MessageType: automationNotification
    Returns dictionary:
    {
    	'lastAutomationDevice':  		<text string>,
		'lastAutomationStatus': 		<text string>,
		'lastAutomationBrightness': 	<text string>,
		'lastAutomationOnState': 		<text string>
	}
