# Harmony Hub

Plugin for the Indigo Home Automation system.

This plugin enables monitoring of certain activities on the Harmony Hub, and provides the capability to send Activity changes and device commands to the Hub.

Communications with the hub uses the pyharmony library along with the sleekxmpp module.  Pyharmony is included with the plugin.  Use pip to install sleekxmpp.


### Broadcast Messages

    PluginID: com.flyingdiver.indigoplugin.harmonyhub

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

### Indigo 7 Only

This plugin only works under Indigo 7 or greater.
