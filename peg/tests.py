# -*- coding: utf-8 -*-
import json
from tatsu import parse
from tatsu.util import asjson


tests = '''create an event on my calendar on wednesday at 4pm
schedule an appointment on madison's schedule tomorrow at noon
put something on milo's calendar on friday at 11 am
what am i up to this week
what does madison have going on today
what is on my schedule today
what is on my schedule today
how busy am i today
what is milo up to this week
what is on my schedule next week
what are madison's events tomorrow
tell me my schedule tomorrow
tell me my lowe schedule next week
add an event to my calendar on march 3rd at 3pm'''


test_lines = tests.split('\n')

def main():
    with open('calendarGrammar.ebnf', 'r') as fObj:
        GRAMMAR = fObj.read()
    
    for x in test_lines:
        print("line: '{}'".format(x))
        ast = asjson(parse(GRAMMAR, x.replace("'s","")))
        print('calendar owner:  {}'.format(ast['calendar_owner']))
        print('time frame: {}'.format(ast['time_frame']))
        print()
        


if __name__ == '__main__':
    main()

