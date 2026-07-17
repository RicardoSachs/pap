# src/vendors/bloomberg.py
# ---------------------------------------------------------------
# Bloomberg blpapi client helpers: session management and BDP/reference-
# data request wrappers, returning pandas DataFrames.

import blpapi
import pandas as pd
from typing import Iterable, Dict, Any
import itertools

def start_session(session = blpapi.Session()):

    if not session.start():
        raise ValueError("Failed to start session.")

    return session

def get_securityData(toPy_list, subservice):
    """
    Pulls the security data from a .toPy (response.toPy()['securityData'])
    
    :param toPy_list: response.toPy() list
    :param subservice: Type of request (Historical or Reference)

    returns a list in which each element is a dict corresponding to a security
    a.k.a. response.toPy()['securityData']
    """
    securityData = map(lambda x:x['securityData'], toPy_list)

    if subservice == 'HistoricalDataRequest':
        return [*securityData]
    elif subservice == 'ReferenceDataRequest':
        #Aditional step: flatten the list
        return [*itertools.chain.from_iterable(securityData)]

def secdata_to_df(sec_data):
    """
    :param sec_data: response.toPy()['securityData'] or equivalent
    so input is a dict in shape {'security':id, 'eidData':[], ..., 'fieldaData':[{}]}
    """
    if type(sec_data['fieldData']) is list:
        ind = None
    else:
        ind = [0]

    df = pd.DataFrame(sec_data['fieldData'], index=ind)\
    .assign(id = sec_data['security'])
    return df

def secdata_list_to_df(sec_data_list):
    df = pd.concat(map(secdata_to_df, sec_data_list)).reset_index(drop=True)
    return df

def create_request(session, subservice):
    
    SERVICE = "//blp/refdata"
    SUB_SERVICE = subservice
    
    if not session.start():
        raise ValueError("Failed to start session.")

    if not session.openService(SERVICE):
        raise ValueError(f"Failed to open {SERVICE}")
    
    service = session.getService(SERVICE)
    request = service.createRequest(SUB_SERVICE)

    return request

def data_request(
    securities: Iterable[str],
    fields: Iterable[str],
    start_date: str | None = None,
    end_date: str | None = None,
    options: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """
    Generate named arguments dictionary of historical data Bloomberg API "a la BDH"
    
    :param securities: Iterable of tickers parsekeyables or other IDs (ISIN, CUSIP, etc)
    :type securities: Iterable[str]
    :param fields: FLDS fields
    :type fields: Iterable[str]
    :param start_date: Start date string
    :type start_date: str | None
    :param end_date: End date string
    :type end_date: str | None
    :param options: Optional arguments / overrides
    :type options: Dict[str, Any] | None
    :return: Named arguments dictionary 
    :rtype: Dict[str, Any]
    """

    # Raise error if missing mandatory parameters
    if securities is None:
        raise ValueError('securities is required')
    if fields is None:
        raise ValueError('fields is required')
    
    # Handle atomic strings, convert to len=1 list
    if type(securities) is str:
        securities = [securities]
    if type(fields) is str:
        fields = [fields]

    return {
        'securities': list(securities),
        'fields': list(fields),
        'start_date': start_date,
        'end_date': end_date,
        'options': options or {}
    }

def fetch_request(session, subservice, options):

    try:
        request = create_request(session=session, subservice=subservice)
    except ValueError as e:
        print(f'Error {e}')
        return

    # Mandatory parameters
    SECURITIES = blpapi.Name("securities")
    FIELDS = blpapi.Name("fields")    

    # Optional parameters (depends if historical or reference)
    START_DATE = blpapi.Name("startDate")
    END_DATE = blpapi.Name("endDate")

    # NAMES = {
    #     'currency': blpapi.Name('currency'),
    #     'periodicitySelection': blpapi.Name("periodicitySelection"),
    #     'pricingOption': blpapi.Name('pricingOption')
    # }

    # Add securities to request
    request[SECURITIES] = options['securities']

    # Add fields to request
    request[FIELDS] = options['fields']

    # Set start and end date
    if options['start_date'] is not None:
        request[START_DATE] = options['start_date'].replace('-','')

    if options['end_date'] is not None:
        request[END_DATE] = options['end_date'].replace('-','')

    # Set optional parameters
    for key, value in options['options'].items():
        request[blpapi.Name(key)] = value

    session.sendRequest(request)

    # responses are event elements appended, defined as messages (msg) by this module 
    responses = []

    done = True
    while done:
        event = session.nextEvent()
        for msg in event:
            if msg.messageType() == blpapi.Names.REQUEST_FAILURE:
                print("Request failed! returning raw messages")
                done = False
                return responses #break
        if event.eventType() == blpapi.Event.PARTIAL_RESPONSE:
            responses.append(msg)
        elif event.eventType() == blpapi.Event.RESPONSE:
            responses.append(msg)
            break
    
    toPys = [*map(lambda x:x.toPy(), responses)]

    try:
        df = secdata_list_to_df(get_securityData(toPys, subservice=subservice))
    except ValueError as e:
        print(f'Response parsing error: {e}')
        return toPys

    return df

def fetch_historical_request(options):
    session = blpapi.Session()
    return fetch_request(session, 'HistoricalDataRequest', options)

def fetch_reference_request(options):
    session = blpapi.Session()
    return fetch_request(session, 'ReferenceDataRequest', options)
