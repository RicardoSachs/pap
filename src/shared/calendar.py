
from datetime import date

def today():
    return date.today()

def is_business_day(d):
    return d.weekday() < 5
