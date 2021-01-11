# Nextcloud Calendar Skill

### Manage you Nextcloud Calendar with Mycroft
* Create events
* List events up to 2 weeks out
* Supports multiple calendars

### Examples
```
"Create an appointment on my schedule tomorrow at 1 PM"
        "how much time will this event take?"
"One hour."
        "what would you like to call this event?"
"Doctor appointment"
        "please confirm my addition of doctor appointment on Thursday January 9th from 1pm to 2pm to your calendar."
"Yes."
        "your calendar has been updated."
```
```
"Tell me my schedule this week"
    "doctor appointment on Thursday January 9th from 1pm to 2pm, soccer match on Saturday January 11th from 9am to 12pm"
```

### Installing
At this time, it is not suggested to directly install from this repo due to the necessity to edit some of the code to tailor to your preferences. See the known issues below. Instead, fork this repo, make your edits, and install with `mycroft-msm https://github.com/<your-github-account>/<your-repo-name>.git`.

### Known issues
* "what are my events on Wednesday?" and similar phrases trigger the Date and Time skill, and Mycroft will just tell you the date on Wednesday. For best results, use "tell me my schedule on friday" or "how busy am I tomorrow".
* To use with your Nextcloud account, you will need to edit the `__init__()` function in `__init__.py` to use you own  calendarToName and nameToCalendar dictionaries, as well as `peg/calendarGrammar.ebnf` so the `ownership` rule reflects you desired names. After doing this, you will need to re-run `generateModel.sh` to regenerate `calendarGrammar.py`.
* Often, attempts to create an event initially specifying both the start time and the duration will not work as expected. Mycroft will often stop recording audio before you finish speaking, and whichever component is cut off will need to be reiterationed when Mycroft prompts for it. E.g. "add and event to my calendar on thursday at 11:30am for 2 hours" may result in Mycroft asking for the duration of the event.
