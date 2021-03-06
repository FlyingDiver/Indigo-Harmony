# Harmony Hub

Plugin for the Indigo Home Automation system.

This plugin enables monitoring of certain activities on the Harmony Hub, and provides the capability to send Activity changes and device commands to the Hub.

The plugin requires XMPP be enabled on your Harmony Hub.  See https://support.logi.com/hc/en-001/community/posts/360032837213-Update-to-accessing-Harmony-Hub-s-local-API-via-XMPP for instructions.

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
