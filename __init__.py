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
import peg
import json

from tatsu.util import asjson
from datetime import datetime as dt
from datetime import timedelta
from datetime import timezone
from adapt.intent import IntentBuilder
from mycroft.skills.core import MycroftSkill
from mycroft.skills.core import intent_handler
from mycroft.util.parse import extract_duration, extract_datetime, normalize

class NextcloudCalendarSkill(MycroftSkill):
    def __init__(self):
        super(NextcloudCalendarSkill, self).__init__(name="NextcloudCalendarSkill")
        
        self.calendarToName = {'madison-1':"madison's",'personal':'your','milo':"milo's"}
        self.nameToCalendar = {"madison":'madison-1', "madison's":'madison-1',
                          "milo's":'milo', "milo":"milo",
                          "my lowe":'milo', "my lowe's":'milo',
                          "my low":"milo", "my low's":"milo",
                          "me":"personal", "my":"personal", "i":"personal",
                          "mine":"personal", "myself":"personal", "my own": "personal",
                          "9": "personal", "mind": "personal"} # add a few similar-sounding words
        
        self.PEGParser = peg.parser()
    
    def getConfigs(self):
        try:
            config = self.config_core.get("NextcloudCalendarSkill", {})
            if not config == {}:
                server_url = str(config.get("server_url"))
                user = str(config.get("user"))
                password = str(config.get("password"))

            else:
                server_url = str(self.settings.get("server_url"))
                user = str(self.settings.get("user"))
                password = str(self.settings.get("password"))
            
            return server_url, user, password
        except Exception as e:
            self.speak_dialog('settings.error')
            self.log.error(e)
            return None, None, None
    
    def convertSpokenTimeRangeToDT(self, time_range_string):
        time_range_list = time_range_string.split(' ')
        # attempt to get starting datetime directly
        try:
            # try using mycroft's parser to get the start time
            extracted_dt= extract_datetime(time_range_string)
            if extracted_dt is None:
                # is likely 'this week' or 'this weekend'
                if 'week' in time_range_list:
                    start = dt.now()
                elif 'weekend' in time_range_list:
                    # next upcoming saturday
                    now = dt.now()
                    current_dow = now.weekday()
                    offset = 5 - current_dow
                    if offset <= 0:
                        offset = 0
                    
                    if 'next' in time_range_list:
                        offset += 7
                        
                    start = dt(now.year, now.month, now.day) + timedelta(offset)
                else:
                    self.speak("i could not parse the given time range")
                    assert False, "key word not supported."
                        
            else:
                # 'next week' will get parsed undesireably by extract_datetime
                if time_range_string == "next week":
                    # get next upcoming sunday
                    now = dt.now()
                    current_dow = now.weekday()
                    offset = 6 - current_dow
                    if offset == 0:
                        offset = 7
                    start = dt(now.year, now.month, now.day) + timedelta(offset)
                    
                else:
                    start = extracted_dt[0]
            
            # now that the start time is found get the end time from the time string
            if 'day' in time_range_string or 'tomorrow' in time_range_string:
                # handles today, monday, tuesday, etc
                end = dt(start.year, start.month, start.day, 23, 59) # end on 11:59pm of same day
            
            elif 'weekend' in time_range_string:
                end = dt(start.year, start.month, start.day, 23, 59) + timedelta(1)
            
            elif 'week' in time_range_string:
                starting_dow = start.day
                if starting_dow == 6:
                    end = dt(start.year, start.month, start.day, 23, 59) + timedelta(6)
                else:
                    end = dt(start.year, start.mongth, start.day, 23, 59) + timedelta(5-starting_dow)
            else: # afternoon, evening, morning
                end = start + timedelta(hours=4)
            
            return start, end
                
            
        except Exception as e:
            self.speak("i could not parse given time range")
            self.log.error(e)
        
        
    def makeEventString(self, name, start, end, rule=None):
        tstamp = dt.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        start_utc = start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        end_utc = end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        _id = hashlib.sha1(bytes(tstamp+name,'utf-8')).hexdigest()
        if rule is not None:
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
    
    def makeEvent(self, calendarObj, start, end, name, rule=None, owner='your'):
        eventString = self.makeEventString(name, start, end, rule=rule)
        try:
            _ = calendarObj.save_event(eventString)
            self.speak_dialog('event.created',{'owner':owner})
            
        except Exception as e:
            self.speak_dialog('caldav.error',{"method":"creating","kind":"event"})
            self.log.error(e)
            
    def searchEvents(self, calendarObj, start, end):
        events = []
        _events = calendarObj.date_search(start=start.astimezone(timezone.utc),
                                          end=end.astimezone(timezone.utc))
        
        for e in _events:
            event_dict = {'name': e.vobject_instance.vevent.summary.value.strip(),
                          'start': e.vobject_instance.vevent.dtstart.value, # will need to convert to TZ
                          'end': e.vobject_instance.vevent.dtend.value # convert to local tz
                          }
            events.append(event_dict)
            self.log.info('start dt: {}'.format( e.vobject_instance.vevent.dtstart.value))
        
        return events
    
    def speakEvents(self, events):
        for e in events:
            duration_str = self.confirmEventDetails(e['start'], e['end'])
            self.speak(e['name'] + ' ' + duration_str)
            for _ in range(1000):                       # small delay to space out events
                pass
            
    def getCalendar(self, calendar_name, url, user, password):
        try:
            URL = 'https://{}/remote.php/dav/calendars/{}'.format(url,user)
            calURL = '{}/{}'.format(URL,calendar_name)
            self.log.info('calendar url: {}'.format(calURL))
            client = caldav.DAVClient(url=URL, username=user, password=password)
            calendar = caldav.Calendar(client=client, url=calURL)
            return calendar
        
        except Exception as e:
            self.speak_dialog('caldav.error',{"method":"accessing","kind":"calendar"})
            self.log.error(e)
            return None
        
    def getAllCalendars(self, url, user, password):
        try:
            URL = 'https://{}/remote.php/dav/calendars/{}'.format(url,user)
            principal = caldav.DAVClient(url=URL, username=user, password=password).principal()
            calendars = principal.calendars()
            for c in calendars:
                self.log.info('got calendar {}'.format(c.name))
            return calendars
        
        except Exception as e:
            self.speak_dialog('caldav.error')
            self.log.error(e)
            return None
        
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
    
    def confirmEventDetails(self, start, end):
        ordinal = lambda n: "%d%s" % (n,"tsnrhtdd"[(n//10%10!=1)*(n%10<4)*n%10::4])
        monthString = ['','January','February','March','April','May','June','July',
                       'August','September','October','November','December']
        dow = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
        # assume nothing lasts longer than a year, so month and day being equivalent is
        # good enough to assume it starts and ends on the same day
        if start.month == end.month and start.day == end.day:
            confirmationText = "on {} {} {} from {} to {}".format(dow[start.weekday()],
                                                                  monthString[start.month],
                                                                  ordinal(start.day),
                                                                  self.timeTextFriendly(start.hour,
                                                                                     start.minute),
                                                                  self.timeTextFriendly(end.hour,
                                                                                     end.minute))
        else:
            confirmationText = "from {} {} {} to {} {} {}".format(dow[start.weekday()],
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
        time_delta,remaining_utt = extract_duration(utt)            # get time duration from utterance
        start_time,remaining_utt = extract_datetime(remaining_utt)  # get time from utterance
        owner = message.data.get('Owner')                           # get calendar owner
        self.log.info("data: {}".format(message.data))
        
        if owner is None:
            owner = self.get_response('ask.calendar.owner')
        
        self.log.info('using owner: {}'.format(owner))
        
        try:
            calName = self.nameToCalendar[owner]
        except KeyError:
            self.speak_dialog('no.calendar.found.error',{'name':owner})
            return
        
        if start_time is None:
            start_time,_ = extract_datetime(self.get_response('ask.start.time'))
        
        if time_delta is None:
            time_delta,_ = extract_duration(self.get_response('ask.duration'))
            
        if time_delta is None or start_time is None:
            self.speak('sorry. i was not able to understand. please start over.')
            return
        
        end_time = start_time + time_delta
        
        eventName = self.get_response('ask.event.name').title()
        
        # verify parameters
        confirmation = self.ask_yesno('confirm.event',
                                      {'event_name': eventName,
                                       'confirmation_text': self.confirmEventDetails(start_time,
                                                                                     end_time),
                                       'owner': self.calendarToName[calName]})
        if confirmation == 'no':
            self.speak_dialog('confirmation.failed')

        elif confirmation == 'yes':        
            url, user, password = self.getConfigs()
            if url is None:
                pass
            else:
                calendar = self.getCalendar(calName, url, user, password)
                self.makeEvent(calendar, start_time, end_time, eventName, owner=self.calendarToName[calName])
        else:
            self.speak('sorry i did not understand.')

    @intent_handler(IntentBuilder("ListEvents").require("List").one_of("Calendar","Time"))
    def handle_list_events_intent(self, message):
        utt = message.data['utterance']
        # normalize and drop "****'s"
        utt = normalize(utt).replace("'s","")
        try:
            ast = self.PEGParser.parse(utt)
            parsed_utt = asjson(ast)
            
            calendar_owner = parsed_utt.get('calendar_owner')
            calendar_timeframe = parsed_utt.get('time_frame')
        except Exception as e:
            self.speak('there was an error parsing your utternace')
            self.log.error(e)
            return
        
        if calendar_owner == None:
            calendar_owner = 'my'
        
        # parser will return list if timeframe is two words (e.g. ["this", "weekend"])
        if type(calendar_timefram) == list:
            calendar_timeframe = ' '.join(calendar_timeframe)
        
        start,end = self.convertSpokenTimeRangeToDT(calendar_timeframe)
        
        url, user, password = self.getConfigs()
        calendarObj = self.getCalendar(self.nameToCalendar[calendar_owner], url, user, password)
        events = self.searchEvents(calendarObj, start, end)
        self.speakEvents(events)

    def stop(self):
        pass
    
def create_skill():
    return NextcloudCalendarSkill()