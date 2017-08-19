# Harmony Hub

Plugin for the Indigo Home Automation system.

This plugin enables monitoring of certain activities on the Harmony Hub, and provides the capability to send Activity changes and device commands to the Hub.

This version of the plugin requires Indigo 7.

**PluginID**: com.flyingdiver.indigoplugin.harmonyhub



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
