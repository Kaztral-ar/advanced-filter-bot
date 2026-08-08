class Messages(object):

    START_MSG = """<b>Hey {},

I'm an advanced filter bot with no practical limit on the number of filters
I can hold per group.

See /help for commands and more details.</b>
"""

    HELP_MSG = """
<i>Add me as admin in your group and start filtering :)</i>


<b>Filter Commands (group admins);</b>

<code>/add keyword reply</code>  -  Add a filter. Reply to a message with
<code>/add keyword</code> to save its text/media/buttons instead.
Use <code>alias1|alias2|alias3</code> as the keyword to trigger one filter
from multiple words.

<code>/del keyword [keyword2 ...]</code>  -  Delete one or more filters

<code>/delall</code>  -  Delete every filter in the chat (owner/auth only)

<code>/viewfilters</code>  -  List all filters in this chat

<code>/exportfilters</code>  -  Download all filters as a JSON backup

<code>/importfilters</code>  -  Reply to an exported JSON file to restore filters


<b>Button syntax (inside a filter's reply text);</b>

<code>[Button text](buttonurl:https://example.com)</code>
<code>[Button text](buttonalert:Text shown on tap)</code>
Add <code>:same</code> after the URL/alert to put it on the same row as the
previous button.


<b>Connection Commands;</b>

<code>/connect groupid</code>  -  Connect a group to manage its filters from
my PM. You can also just run <code>/connect</code> inside the group.

<code>/connections</code>  -  Manage your connections

<code>/disconnect</code>  -  Disconnect the current group


<b>Extras;</b>

/id  -  Shows chat/user ID information
<code>/info [userid]</code>  -  Shows user information; reply to a message
to look up its sender
/status  -  Bot status (auth users only)
<code>/broadcast</code>  -  Reply to a message to send it to every known user (auth only)
<code>/ban userid [reason]</code> / <code>/unban userid</code>  -  Block/unblock bot access (auth only)
"""

    ABOUT_MSG = """<b>Filter Bot</b>

<b>Maintained by :</b> @k4tral
<b>Language :</b> <code>Python 3</code>
<b>Library :</b> <a href='https://docs.pyrogram.org/'>Pyrogram</a>
<b>Database :</b> MongoDB (motor / async)
"""
