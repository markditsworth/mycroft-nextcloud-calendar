# Copyright 2021 M. Ditsworth
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import caldav
import hashlib
import json

from .peg import parser
from tatsu.util import asjson
from datetime import datetime as dt
from datetime import timedelta
from datetime import timezone
from adapt.intent import IntentBuilder
from mycroft.skills.core import MycroftSkill
from mycroft.skills.core import intent_handler
from mycroft.util.parse import extract_duration, extract_datetime, normalize
from mycroft.util.time import default_timezone

class NextcloudCalendarSkill(MycroftSkill):
    def __init__(self):
        super(NextcloudCalendarSkill, self).__init__(name="NextcloudCalendarSkill")
        
        # dictionary to convert calendar names to corresponding possessives
        self.calendarToName = {'madison-1':"madison's",'personal':'your','milo':"milo's"}
        # dictionary to convert possible possessives to corresponding calendar names
        self.nameToCalendar = {"madison":'madison-1', "madison's":'madison-1',
                          "milo's":'milo', "milo":"milo",
                          "my lowe":'milo', "my lowe's":'milo',
                          "my low":"milo", "my low's":"milo",
                          "me":"personal", "my":"personal", "i":"personal",
                          "mine":"personal", "myself":"personal", "my own": "personal",
                          "9": "personal", "mind": "personal"}
        # init custom timeframe and calendar owner parser
        self.PEGParser = parser()
    
    # get skill configurations from home.mycroft.ai or from local settings
    def getConfigs(self):
        try:
            config = self.config_core.get("NextcloudCalendarSkill", {})
            if not config == {}:
                server_url = str(config.get("server_url"))                      # url to nextcloud server
                user = str(config.get("user"))                                  # nextcloud username
                password = str(config.get("password"))                          # nextcloud password

            else:
                server_url = str(self.settings.get("server_url"))
                user = str(self.settings.get("user"))
                password = str(self.settings.get("password"))
            
            return server_url, user, password
        except Exception as e:
            self.speak_dialog('settings.error')
            self.log.error(e)
            return None, None, None                                             # return Nones to signify the error
    
    # convert the spoken time range to start and end datetime objects
    def convertSpokenTimeRangeToDT(self, time_range_string):
        time_range_list = time_range_string.split(' ')
        # attempt to get starting datetime directly
        try:
            extracted_dt= extract_datetime(time_range_string)                   # try using mycroft's parser to get the start time
            if extracted_dt is None:                                            # is likely 'this week' or 'this weekend'
                if 'week' in time_range_list:
                    start = dt.now()                                            # start at current time so as to ignore any of todays
                    self.log.info('got this week')                              # events that have allready passed
                elif 'weekend' in time_range_list:
                    self.log.info('got weekend')
                    now = dt.now()                                              # for 'this weekend' start should be the upcoming sat
                    current_dow = now.weekday()                                 # unless it is already sat or sun. It it is sat or sun
                    offset = 5 - current_dow                                    # start at current time
                    if offset <= 0:
                        offset = 0
                    
                    if 'next' in time_range_list:                               # for 'next weekend', add 7 to the calculated offset
                        offset += 7                                             # from above
                        
                    start = dt(now.year, now.month, now.day) + timedelta(offset)
                else:                                                           # all other key words for time range should be captured
                    self.speak("i could not parse the given time range")        # in the other conditional blocks
                    assert False, "key word not supported."
                        
            else:
                if time_range_string == "next week":                            # 'next week' will get parsed incorrectly by 
                    self.log.info('got next week')                              # extract_datetime
                    now = dt.now()
                    current_dow = now.weekday()                                 # get the upcoming sunday; if it is currently sunday
                    offset = 6 - current_dow                                    # get the following one 
                    if offset == 0:
                        offset = 7
                    start = dt(now.year, now.month, now.day) + timedelta(offset)
                    
                else:                                                           # otherwise use the datetime provided by extract_datetime
                    self.log.info('got something else')
                    start = extracted_dt[0]
            
            # now that the start time is found get the end time from the time string
            if 'day' in time_range_string or 'tomorrow' in time_range_string:   # handles day, today, monday, tuesday, etc
                end = dt(start.year, start.month, start.day, 23, 59)            # end on 11:59pm of same day
            
            elif 'weekend' in time_range_string:                                # start is saturday morn, so end on last min of sunday
                end = dt(start.year, start.month, start.day, 23, 59) + timedelta(1)
            
            elif 'week' in time_range_string:
                starting_dow = start.weekday()                                  # end on the saturday of the given week
                if starting_dow == 6:                                           # if it is sunday, +6 days 23h 59m
                    end = dt(start.year, start.month, start.day, 23, 59) + timedelta(6)
                else:                                                           # if it is not sunday, add the required days + 23:59 to reach sat
                    end = dt(start.year, start.month, start.day, 23, 59) + timedelta(5-starting_dow)
            else:                                                               # afternoon, evening, morning resutls in 4h ranges
                end = start + timedelta(hours=4)
            
            self.log.info("start: {}".format(start))
            self.log.info("end: {}".format(end))
            return start, end
                
            
        except Exception as e:                                                  # log and notify of any errors
            self.speak("i could not parse given time range")
            self.log.error(e)
        
    # convert event name, start and end times (in local time) to ical strings
    def makeEventString(self, name, start, end, rule=None):
        tstamp = dt.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")             # get current time for timestamp
        start_utc = start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")   # convert start and end from local to utc
        end_utc = end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")       # since nextcloud calendar uses UTC
        _id = hashlib.sha1(bytes(tstamp+name,'utf-8')).hexdigest()              # SHA-1 the timestamp+name to give a unique ID
        if rule is not None:                                                    # by default, no repition.
            rrule = "FREQ={}\n".format(rule)
        else:
            rrule = ""
        s = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Sabre//Sabre VObject 4.3.0//EN
BEGIN:VEVENT
UID:{}
DTSTAMP:{}
DTSTART:{}        
DTEND:{}
{}SUMMARY:{}        
END:VEVENT
END:VCALENDAR
"""
        s = s.format(_id, tstamp, start_utc, end_utc, rrule, name)
        return s
    
    # create event in nextcloud calendar
    def makeEvent(self, calendarObj, start, end, name, rule=None, owner='your'):
        eventString = self.makeEventString(name, start, end, rule=rule)         # create the ical string
        try:
            _ = calendarObj.save_event(eventString)                             # send event to Nextcloud calendar
            self.speak_dialog('event.created',{'owner':owner})
            
        except Exception as e:
            self.speak_dialog('caldav.error',{"method":"creating","kind":"event"})
            self.log.error(e)
    
    # call caldav api for events in calendar between start and end
    def searchEvents(self, calendarObj, start, end):
        events = []                                                             # initialize list for events
        _events = calendarObj.date_search(start=start.astimezone(timezone.utc),
                                          end=end.astimezone(timezone.utc))     # pull events from caldav server, with start and end in utc
        
        for e in _events:
            name = e.vobject_instance.vevent.summary.value.strip()
            start = e.vobject_instance.vevent.dtstart.value
            end = e.vobject_instance.vevent.dtend.value

            if type(start) == type(dt.now()):                                   # if start/end are datetimes
                start = start.astimezone(default_timezone())                    # convert to local TZ
                end = end.astimezone(default_timezone())
                                                                                # otherwise, they are dates, and can be left
            event_dict = {'name': name,                                         # build dict with event info
                          'start': start,
                          'end': end
                          }
            events.append(event_dict)                                           # add dict to list
        
        events.reverse()                                                        # events return from caldav server in reverse-chrono order
        return events                                                           # so reverse the list to allow mycroft to read them off in order    
    
    # speak the given list of events
    def speakEvents(self, events):
        for e in events:
            duration_str = self.confirmEventDetails(e['start'], e['end'])       # use the confirmEventDeatils function to get readable string
            self.speak(e['name'] + ' ' + duration_str)
            for _ in range(1000):                                               # small delay between events to sound more natural
                pass
    
    # returns the caldav calendar object for the calendar_name in the given nextcloud account
    def getCalendar(self, calendar_name, url, user, password):
        try:
            URL = 'https://{}/remote.php/dav/calendars/{}'.format(url,user)     # build base URL
            calURL = '{}/{}'.format(URL,calendar_name)                          # add calendar name to URL to get URL to calendar
            self.log.info('calendar url: {}'.format(calURL))
            client = caldav.DAVClient(url=URL, username=user, password=password) # construct the client
            calendar = caldav.Calendar(client=client, url=calURL)               # constuct the calendar object
            return calendar
        
        except Exception as e:
            self.speak_dialog('caldav.error',{"method":"accessing","kind":"calendar"})
            self.log.error(e)
            return None
    
    # return list of all calendars available from nextcloud account
    def getAllCalendars(self, url, user, password):
        try:
            URL = 'https://{}/remote.php/dav/calendars/{}'.format(url,user)     # build base URL
            principal = caldav.DAVClient(url=URL, username=user, password=password).principal() # construct principal
            calendars = principal.calendars()                                   # get list of calendars
            for c in calendars:
                self.log.info('got calendar {}'.format(c.name))                 # log the calendar names (this might not actually work)
            return calendars
        
        except Exception as e:
            self.speak_dialog('caldav.error')
            self.log.error(e)
            return None
    
    # 24H to 12H with am/pm
    def timeTextFriendly(self, hour, minute):
        if hour < 12:
            tod = "am"
        else:
            tod = "pm"
            hour -= 12
            
        if hour == 0:
            H = "12"
        elif hour < 10:
            H = "0" + str(hour)
        else: H = str(hour)
        
        if minute < 10:
            M = "0" + str(minute)
        else:
            M = str(minute)
        
        return "{}:{}{}".format(H,M,tod)
    
    # build a readable string to enumerate the start and end dates and times
    def confirmEventDetails(self, start, end):
        ordinal = lambda n: "%d%s" % (n,"tsnrhtdd"[(n//10%10!=1)*(n%10<4)*n%10::4])
        monthString = ['','January','February','March','April','May','June','July',
                       'August','September','October','November','December']
        dow = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
        # assume nothing lasts longer than a year, so month and day being equivalent is
        # good enough to assume it starts and ends on the same day
        if start.month == end.month and start.day == end.day:                                   # all day events will never start/end on same day
            confirmationText = "on {} {} {} from {} to {}".format(dow[start.weekday()],         # e.g. "on Monday January 4th from 9am to 11am"
                                                                monthString[start.month],
                                                                ordinal(start.day),
                                                                self.timeTextFriendly(start.hour,
                                                                                    start.minute),
                                                                self.timeTextFriendly(end.hour,
                                                                                    end.minute))
        else:
            self.log.info("start: {}".format(start))
            self.log.info("end: ".format(end))
            assert type(start) == type(dt.date(dt.now())), "unsupported multiday event"
            if  end == start + timedelta(1):                                                    # if the event is all day, no need for times
                confirmation_text = "on {} {} {}".format(dow[start.weekday()],
                                                    monthString[start.month],
                                                    ordinal(start.day))
            else:
                end = end + timedelta(-1)
                confirmationText = "from {} {} {} to {} {} {}".format(dow[start.weekday()],         # e.g. "from Monday January 4th to Thursday January 7th"
                                                                  monthString[start.month],
                                                                  ordinal(start.day),
                                                                  dow[end.weekday()],
                                                                  monthString[end.month],
                                                                  ordinal(end.day))
        return confirmationText
    
    @intent_handler(IntentBuilder("RescheduleEvent").require("Reschedule").require("Event"))
    def handle_reschedule_event_intent(self,message):
        self.speak('this skill is in progress')
        
    @intent_handler(IntentBuilder("CancelEvent").require("Cancel").require("Event"))
    def handle_cancel_event_intent(self,message):
        self.speak('this skill is in progress')
        
    @intent_handler(IntentBuilder("AddEvent").require("Add").require("Event").
                    require("Calendar").optionally("Whose.Calendar"))
    def handle_add_event_intent(self,message):
        utt = message.data['utterance']
        time_delta,remaining_utt = extract_duration(utt)                        # get time duration from utterance
        start_time,remaining_utt = extract_datetime(remaining_utt)              # get time from utterance
        owner = message.data.get('Owner')                                       # get calendar owner
        utt = normalize(utt).replace("'s","")                                   # normalize and drop 's in utterance
        parsed_utt = asjson(self.PEGParser.parse(utt))                                # parse utterance for owner
        owner = parsed_utt.get('calendar_owner')
        if owner is None:                                                       # if parser failed to get owner, prompt user
            owner = self.get_response('ask.calendar.owner')
        
        self.log.info('using owner: {}'.format(owner))
        
        try:                                                                    # get the calendar belonging to owner
            calName = self.nameToCalendar[owner]                                # throw error if none found
        except KeyError:
            self.speak_dialog('no.calendar.found.error',{'name':owner})
            return
        
        if start_time is None:                                                  # if start time not found
            start_time,_ = extract_datetime(self.get_response('ask.start.time'))# ask the user
        
        if time_delta is None:                                                  # if duration not found
            time_delta,_ = extract_duration(self.get_response('ask.duration'))  # ask the user
            
        if time_delta is None or start_time is None:                            # if duration of start time STILL unkonwn
            self.speak('sorry. i was not able to understand. please start over.') # fail
            return
        
        end_time = start_time + time_delta                                      # calculate end time
        
        eventName = self.get_response('ask.event.name').title()                 # ask for event name
        
        confirmation = self.ask_yesno('confirm.event',                          # confirm details
                                      {'event_name': eventName,
                                       'confirmation_text': self.confirmEventDetails(start_time,
                                                                                     end_time),
                                       'owner': self.calendarToName[calName]})
        if confirmation == 'no':
            self.speak_dialog('confirmation.failed')

        elif confirmation == 'yes':        
            url, user, password = self.getConfigs()                             # get  configs
            if url is None:                                                     # if getConfigs returned None, it failed and
                pass                                                            # already spoke to user
            else:               
                calendar = self.getCalendar(calName, url, user, password)       # get calendar and create the event
                self.makeEvent(calendar, start_time, end_time, eventName, owner=self.calendarToName[calName])
        else:
            self.speak('sorry i did not understand.')

    @intent_handler(IntentBuilder("ListEvents").require("List").one_of("Calendar","Time"))
    def handle_list_events_intent(self, message):
        utt = message.data['utterance']
        utt = normalize(utt).replace("'s","")                                   # normalize and drop "****'s"
        try:
            ast = self.PEGParser.parse(utt)                                     # parse utterance for owner and time frame
            parsed_utt = asjson(ast)
            
            calendar_owner = parsed_utt.get('calendar_owner')                   # use .get() to return None if key not found
            calendar_timeframe = parsed_utt.get('time_frame')                   # rather than error-ing out on a failed ['<key>']    
        except Exception as e:
            self.speak('there was an error parsing your utternace')
            self.log.error(e)
            return
        
        if calendar_owner == None:                                              # if owner not found, default to personal calendar
            calendar_owner = 'my'
        
        # parser will return list if timeframe is two words (e.g. ["this", "weekend"]) and convertSpokenTimeRangeToDT
        # takes a string as input, so join with space if calendar_timeframe is a list
        if type(calendar_timeframe) == list:
            calendar_timeframe = ' '.join(calendar_timeframe)
        
        start,end = self.convertSpokenTimeRangeToDT(calendar_timeframe)         # generate the start and end times for the event search
        
        url, user, password = self.getConfigs()                                 # get config settings
        calendarObj = self.getCalendar(self.nameToCalendar[calendar_owner],     # construct caldav calendar object
                                       url, user, password)
        events = self.searchEvents(calendarObj, start, end)                     # get list of events between start and end
        self.speakEvents(events)                                                # speak those events

    def stop(self):
        pass
    
def create_skill():
    return NextcloudCalendarSkill()