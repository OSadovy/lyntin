#######################################################################
# This file is part of Lyntin.
# copyright (c) Free Software Foundation 2001, 2002
#
# Lyntin is distributed under the GNU General Public License license.  See the
# file LICENSE for distribution details.
# $Id: action.py,v 1.1 2003/05/05 05:56:02 willhelm Exp $
#######################################################################
"""
This module defines the ActionManager which handles managing actions 
(triggers), matching triggers in mud_data and executing the resulting
action on behalf of the user for that session.

The ActionManager contains an ActionData object for every session that
has actions.

An action consists of:

1. the trigger statement
2. the response statement
3. the priority of the action
4. whether or not the action is a onetime action

We also store a compiled regular expression of the trigger which
we use on incoming mud_data to check for triggered actions.

The compiled regular expressions gets recompiled every time a variable
changes--this allows us to handle Lyntin variables in the action trigger
statements.
"""
import re, string, copy
from lyntin import manager, utils, event, __init__, hooks, exported, ansi
from lyntin.modules import modutils

# the placement variable regular expression
VARREGEXP = re.compile('%_?(\d+)')


class ActionData:
  def __init__(self, ses):
    self._actions = {}
    self._ses = ses

  def addAction(self, trigger, response, priority=5, onetime=0):
    """
    Compiles a trigger pattern and adds the entire action to the
    hash.

    @param trigger: the trigger pattern
    @type  trigger: string

    @param response: what to do when the trigger pattern is found
    @type  response: string

    @param priority: the priority to run this action at.  actions
        are sorted by priority then by the trigger statement when
        we go to check for triggered actions.  default is 5
    @type  priority: int

    @param onetime: if the trigger is found, should this action then
        get removed after the response is executed
    @type  onetime: boolean

    @return: 1
    @rtype:  boolean
    """
    expansion = exported.expand_ses_vars(trigger, self._ses)
    if not expansion:
      expansion = trigger
    compiled = utils.compile_regexp(expansion, 1)
    self._actions[trigger] = (trigger, compiled, response, priority, onetime)
    return 1

  def _recompileRegexps(self):
    """
    When a variable changes, we go through and recompile all the
    regular expressions for the actions in this session.
    """
    for mem in self._actions.keys():
      (trigger, compiled, response, priority, onetime) = self._actions[mem]
      expansion = exported.expand_ses_vars(trigger, self._ses)
      if not expansion:
        expansion = trigger

      compiled = utils.compile_regexp(expansion, 1)

      self._actions[trigger] = (trigger, compiled, response, priority, onetime)

  def clear(self):
    """
    Clears all the stored actions from the action manager.
    """
    self._actions.clear()

  def removeActions(self, text):
    """
    Removes actions that match the given text from the list and
    returns the list of actions that were removed so the calling
    function knows what actually happened.

    @param text: all actions that match this text pattern will 
        be removed.  the text pattern is "expanded" by 
        "utils.expand_text"
    @type  text: string

    @return: list of tuples (trigger, response) of the action
        that were removed.
    @rtype: (string, string)
    """
    badactions = utils.expand_text(text, self._actions.keys())

    ret = []
    for mem in badactions:
      ret.append((self._actions[mem][0], self._actions[mem][2]))
      del self._actions[mem]

    return ret

  def getActions(self):
    """
    Returns a list of all the actions this actionmanager is currently
    managing.

    @return: list of triggers for the actions we're managing.
    @rtype: list of strings
    """
    listing = self._actions.keys()
    listing.sort()
    return listing

  def checkActions(self, text):
    """
    Checks to see if text triggered any actions.  Any resulting 
    actions will get added as an InputEvent to the queue.

    @param text: the data coming from the mud to check for triggers
    @type  text: string
    """
    # FIXME - make sure this works even when lines are broken up.
    matched = []

    actionlist = self._actions.values()
    actionlist.sort(lambda x,y:cmp(x[3], y[3]))

    # go through all the lines in the data and see if we have
    # any matches
    for (action, actioncompiled, response, priority, onetime) in actionlist:
      line = utils.filter_cm(ansi.filter_ansi(text))
      match = actioncompiled.search(line)
      if match:
        # for every match we figure out what the expanded response
        # is and add it as an InputEvent in the queue.  the reason
        # we do a series of separate events rather than one big
        # event with ; separators is due to possible issues with 
        # braces and such in malformed responses.

        # get variables from the action
        actionvars = get_ordered_vars(action)

        # fill in values for all the variables in the match
        varvals = {}
        for i in xrange(len(actionvars)):
          varvals[actionvars[i]] = match.group(i+1)

        # add special variables
        varvals['a'] = line.replace(';', '_')
            
        # fill in response variables from those that
        # matched on the trigger
        response = utils.expand_vars(response, varvals)

        # event.InputEvent(response, internal=1, ses=self._ses).enqueue()
        try:
          exported.lyntin_command(response, internal=1, session=self._ses)
        except:
          exported.write_traceback()

        if onetime:
          del self._actions[action]


  def getStatus(self):
    """
    Returns a one-liner as to how many actions we have.

    @return: a description of the status of this manager
    @rtype:  string
    """
    return "%d action(s)." % len(self._actions)

  def getInfo(self, text=""):
    """
    Returns information about the actions in here.

    This is used by #action to tell all the actions involved
    as well as #write which takes this information and dumps
    it to the file.

    @param text: the text to expand to find actions the user
        wants information about.
    @type  text: string

    @return: a string containing all the action information
    @rtype: string
    """
    if len(self._actions.keys()) == 0:
      return ''

    if text=='':
      listing = self._actions.keys()
    else:
      listing = utils.expand_text(text, self._actions.keys())

    data = []
    for mem in listing:
      actup = self._actions[mem]

      data.append("%saction {%s} {%s} priority={%d} onetime={%s}" % 
              (__init__.commandchar, utils.escape(mem), 
               utils.escape(actup[2]), actup[3], actup[4]))

    return string.join(data, "\n")

  def getCount(self):
    """
    Returns how many aliases we're managing.

    @return: the number of actions being managed.
    @rtype: int
    """
    return len(self._actions)


class ActionManager(manager.Manager):
  def __init__(self):
    self._actions = {}

  def addAction(self, ses, trigger, response, priority, onetime=0):
    if not self._actions.has_key(ses):
      self._actions[ses] = ActionData(ses)
    return self._actions[ses].addAction(trigger, response, priority, onetime)
    
  def clear(self, ses):
    if self._actions.has_key(ses):
      self._actions[ses].clear()

  def removeActions(self, ses, text):
    if self._actions.has_key(ses):
      return self._actions[ses].removeActions(text)
    return []

  def getActions(self, ses):
    if self._actions.has_key(ses):
      return self._actions[ses].getActions()
    return []

  def checkActions(self, ses, text):
    if self._actions.has_key(ses):
      self._actions[ses].checkActions(text)

  def getInfo(self, ses, text=""):
    if self._actions.has_key(ses):
      return self._actions[ses].getInfo(text)
    return ""

  def addSession(self, newsession, basesession=None):
    if basesession:
      if self._actions.has_key(basesession):
        acdata = self._actions[basesession]._actions
        for mem in acdata.keys():
          self.addAction(newsession, mem, acdata[mem][2], acdata[mem][3], acdata[mem][4])

  def removeSession(self, ses):
    if self._actions.has_key(ses):
      del self._actions[ses]

  def getStatus(self, ses):
    if self._actions.has_key(ses):
      return self._actions[ses].getStatus()
    return "0 action(s)."

  def persist(self, args):
    """
    write_hook function for persisting the state of our session.
    """
    ses = args[0]
    file = args[1]
    quiet = args[2]

    data = self.getInfo(ses)
    if data:
      if quiet == 1:
        data = data.replace("\n", " quiet={true}\n")
        file.write(data + " quiet={true}\n")
      else:
        file.write(data + "\n")
      file.flush()

  def variableChange(self, args):
    """
    When a variable changes, we need to recompile the regular
    expressions involved.  This facilitates that.

    This is registered with the variable_change hook.
    """
    ses = args[0]
    if self._actions.has_key(ses):
      self._actions[ses]._recompileRegexps()

  def mudfilter(self, args):
    """
    mud_filter_hook function to check for actions when data
    comes from the mud.
    """
    ses = args[0]
    text = args[-1]

    if not ses._ignoreactions:
      self.checkActions(ses, text)
    return text


def get_ordered_vars(text):
  """
  Takes in a string and removes any ordered variables
  from it.  Returns a list of the variables.

  @param text: the incoming string which may have ordered variables in it.
  @type  text: string

  @return: list of strings of the form '%[0-9]+' for ordered variable
      substitution.
  @rtype: list of strings
  """
  keylist = []
  matches = VARREGEXP.findall(text)

  for match in matches:
    keylist.append(match)

  return keylist

commands_dict = {}

def action_cmd(ses, args, input):
  """
  With no trigger and no action, prints all actions.
  With a trigger and no action, prints actions that match the
  trigger statement.
  With a trigger and an action, creates an action.

  When data from the mud matches the trigger clause, the response
  will be executed.  Trigger clauses can use anchors (^ and $)
  to anchor the text to the beginning and end of the line 
  respectively.

  Triggers can also contain Lyntin pattern-variables which start
  with a % sign and have digits: %0, %1, %10...  When Lyntin sees 
  a pattern-variable in an action trigger, it tries to match any 
  pattern against it, and saves any match it finds so you can 
  use it in the response.  See below for examples.

  Note: As a note, actions are matched via regular expressions.
  %1 gets translated to (.+?) and %_1 gets translated to (\S+?).
  The special variable "%a" means "the whole matched line".

  We handle regular expressions with a special r[ ... ] syntax.  If
  you put an "i" or "I" after the ], then we'll ignorecase as well.

  The onetime argument can be set to true to have the action remove
  itself automatically after it is triggered.

  examples:
    #action {^You are hungry} {get bread bag;eat bread}
    #action {%0 gives you %5} {say thanks for the %5, %0!}
    #action {r[^%_1 tells\\s+you %2$]} {say %1 just told me %2}
    #action {r[sven dealt .+? to %1$]i} {say i just killed %1!}

  category: commands
  """
  trigger = args["trigger"]
  action = args["action"]
  priority = args["priority"]
  onetime = args["onetime"]
  quiet = args["quiet"]

  am = exported.get_manager("action")

  # they typed '#action'--print out all the current actions
  if not trigger and not action:
    data = am.getInfo(ses)
    if data == '':
      data = "action: no actions defined."

    exported.write_message("actions:\n" + data, ses)
    return

  # they typed '#action dd*' and are looking for matching actions
  if not action:
    data = am.getInfo(ses, trigger)
    if data == '':
      data = "action: no actions defined."

    exported.write_message("actions:\n" + data, ses)
    return

  try:
    am.addAction(ses, trigger, action, priority, onetime)
    if not quiet:
      exported.write_message("action: {%s} {%s} {%d} added." % (trigger, action, priority), ses)
  except:
    exported.write_traceback("action: exception thrown.", ses)

commands_dict["action"] = (action_cmd, "trigger= action= priority:int=5 onetime:boolean=false quiet:boolean=false")

def unaction_cmd(ses, args, input):
  """
  Removes action(s) from the manager.

  examples:
    #unaction {missed you.}
    #unaction missed*

  category: commands
  """
  am = exported.get_manager("action")
  func = am.removeActions
  modutils.unsomething_helper(args, func, ses, "action", "actions")

commands_dict["unaction"] = (unaction_cmd, "str= quiet:boolean=false")



am = None

def load():
  """ Initializes the module by binding all the commands."""
  global am, var_module
  modutils.load_commands(commands_dict)
  am = ActionManager()
  exported.add_manager("action", am)

  hooks.mud_filter_hook.register(am.mudfilter, 75)
  hooks.write_hook.register(am.persist)
  hooks.variable_change_hook.register(am.variableChange)


def unload():
  """ Unloads the module by calling any unload/unbind functions."""
  global am, var_module
  modutils.unload_commands(commands_dict.keys())
  exported.remove_manager("alias")
  hooks.mud_filter_hook.unregister(am.mudfilter)
  hooks.write_hook.unregister(am.persist)
  hooks.variable_change_hook.unregister(am.variableChange)


# Local variables:
# mode:python
# py-indent-offset:2
# tab-width:2
# End: