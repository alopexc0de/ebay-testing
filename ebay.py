# Imports first
# This is the sdk found at https://github.com/timotheus/ebaysdk-python
from ebaysdk.trading import Connection as Trading
from ebaysdk.exception import ConnectionError, ConnectionResponseError

# Parallel requires Gevent and Grequests modules to be available on the server (requires at least 2.7.5)
from ebaysdk.parallel import Parallel

import datetime
import csv

# Application Settings
app_id = ''
dev_id = ''
crt_id = ''
domain = 'api.sandbox.ebay.com'

# User Identification
usr_token = ''

# CSV file data
csv_path = ''
csv_delimiter = ','
csv_quote = '\''

# We can probably put the DateRange functions into a class

# Creates a dateRange list for use with glue
def setDateRange(days=None, start=None, rangeType=None):
    # Default to searching for listings ending today
    if days == None:
        days = 0
    else:
        try:
            days = int(days)
        except ValueError:
            days = 0
    if rangeType == None:
        rangeType = 'end'
    else:
        try:
            rangeType = str(rangeType)
        # This shouldn't happen, but you never know users
        except ValueError: 
            rangeType = 'end'

    if start == None:
        # Begin the search at the current timestamp
        today = datetime.datetime.today()
    elif type(start) == 'datetime.datetime':
        today = start
    elif type(start) == 'str':
        try:
            # Try to cast the string to the datetime type
            today = datetime.datetime.strptime(start, '%Y-%m-%dT%H:%M:%S.%fZ')
        except ValueError:
            # The string wasn't valid to become a datetime, set to today
            today = datetime.datetime.today()
    else:
        today = datetime.datetime.today()


    # Set the days argument to search forward more than one day
    delta = datetime.timedelta(days)
    
    # End the search at the future timestamp
    future = today+delta
    # Convert our dates into a format that ebay can recognize (ISO 8601)
    today = today.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    # Force the future to be the absolute end of the day
    future = future.strftime("%Y-%m-%dT23:59:59.999Z")

    # If we want to manipulate either today or future, the following converts from a string back into a datetime object
    # datetime.datetime.strptime(today, '%Y-%m-%dT%H:%M:%S.%fZ')
    return {'from': today, 'to': future, 'type': rangeType}

# We call this a couple times, so it gets its own function
def switchDateRange(list=None, range=None):
    # Switch statement to check which type of dateRange to search by
    # Will always return a valid dateRange for use as various itemArgs 
    # Defaults to a dateRange ending today

    if (range == None) | (isinstance(range, dict) != True):
        # Sets the default range (items that are ending today)
        range = setDateRange()

    if (list == None) | (isinstance(list, dict) != True):
        list = {}

    # This can be start/mod/end
    def rangeType(condition=None):
        # No condition to check, defaults to End
        if condition == None:
            return 'End'
        # Cast the condition to a string
        condition = str(condition)
        switch = {
            'start': 'Start', # Covers StartTimeFrom and StartTimeTo - Items that started in this date range
            'mod': 'Mod', # Covers ModTimeFrom and ModTimeTo - Items modified in this date range
            'end': 'End' # Covers EndTimeFrom and EndTimeTo - Items that end within this date range
        }
        # Return the approiate text or End if no ID matches
        return switch.get(condition, 'End')
                
    # Override the dates in sellerList with values from dateRange, if provided  
    if ('from' in range) & ('type' in range):
        # Remove the list of keys from sellerList - We can only have one search range
        for o in ['EndTimeFrom','ModTimeFrom','StartTimeFrom']:
            try:
                del list[o]
            except KeyError:
                continue

        list[rangeType(range['type'])+'TimeFrom'] = range['from']

    if ('to' in range) & ('type' in range):
        # Remove the list of keys from sellerList - We can only have one search range
        for o in ['EndTimeTo','ModTimeTo','StartTimeTo']:
            try:
                del list[o]
            except KeyError:
                continue

        list[rangeType(range['type'])+'TimeTo'] = range['to']

    return list

# Here are the error codes that we currently have
# None - No events have happened yet
# 0 - Everything is fine
# 1 - The API variable is either unset, or is not a valid connection to the ebay API
# 2 - The required list is either unset, or is not the required type - Usually dict, but can be a list of dicts
# 3 - EndTimeFrom or EndTimeTo were not set in the list - getSeller only
# 4 - Relates to 3, but specifically refers to a dateRange not being available for glue
# 5 - No data (useful) returned by API - A field of data we need is None

# minor logic checking - We don't want to get trackbacks for silly reasons
# getSeller gets a list of our itemIDs
def getSeller(api=None, list=None):
    # api is the connection to the Trading API
    # list is a dict containing required information for ebay to search for (http://developer.ebay.com/DevZone/XML/docs/Reference/ebay/GetSellerEvents.html)
    #   - The datapoints that MUST be defined are EndTimeFrom and EndTimeTo - These select the dateRange that items end on ebay
    
    # Set our error conditions
    res = { 'error': { 'code': None, 'msg': None, 'fnc': 'getSeller' }, 'apiResponse': {} }
    if api == None:
        res['error']['code'] = '1'
        res['error']['msg'] = 'api is not set'
        return res
    if (list == None) | (isinstance(list, dict) != True):
        res['error']['code'] = '2'
        res['error']['msg'] = 'list doesn\'t exist or is of wrong type, must be dict'
        return res
    if ('EndTimeFrom' not in list) | ('EndTimeTo' not in list):
        res['error']['code'] = '3'
        res['error']['msg'] = 'either "EndTimeFrom" or "EndTimeTo" is not set in list'
        return res
    
    res['apiResponse'] = api.execute('GetSellerEvents', list).dict()
    
    # Verify that the search returned information
    if res['apiResponse']['ItemArray'] != None:
        # Check if the itemArray is setup the way we want it (list containing one or more dicts)
        try:
            for k in res['apiResponse']['ItemArray']['Item']:
                itemid = k['ItemID']
        except TypeError:
            # The itemArray is not, force it to be then
            res['apiResponse'] = [ res['apiResponse']['ItemArray']['Item'] ]
        else:
            # No need to encase the list in another list
            res['apiResponse'] = res['apiResponse']['ItemArray']['Item']
        
        # Yay no errors
        if res['error']['code'] == None:
            res['error']['code'] = '0'
    else:
        # drop the response as it contains no useful information anymore
        res['apiResponse'] = {} 
        res['error']['code'] = '5'
        res['error']['msg'] = 'no items found - maybe the dateRange is too narrow?'
        
    return res

# getItems uses the list of ItemIDs provided by getSeller to get specific information about each ItemID
def getItems(api=None, itemList=None, itemArgs=None):
    # api is the connection to the Trading API
    # itemList is a dict containing ItemIDs and other info as a result of getSeller
    # itemArgs is an optional dict that contains extra details to refine the search returned by ebay (http://developer.ebay.com/DevZone/XML/docs/Reference/ebay/GetItem.html)
    #   - The two required datapoints in itemArgs are IncludeItemSpecifics and ItemID, both are defined below in the loop
    
    # Set our error conditions
    res = { 'error': { 'code': None, 'msg': None, 'fnc': 'getItems' }, 'apiResponse': {} }
    if api == None:
        res['error']['code'] = '1'
        res['error']['msg'] = 'api is not set'
        return res
    if (itemList == None) | (type(itemList) != type([])):
        res['error']['code'] = '2'
        res['error']['msg'] = 'itemList doesn\'t exist or is of wrong type, must be list containing one or more dicts'
        return res
    if (itemArgs == None) | (isinstance(itemArgs, dict) != True):
        res['error']['code'] = '2'
        res['error']['msg'] = 'itemArgs doesn\'t exist or is of wrong type, must be dict'
        return res
        
    # For each ItemID
    for k in itemList: 
        # Extra arguments that should be applied anyways
        itemArgs['IncludeItemSpecifics'] = 'True'
        # Search for specific ItemID
        itemArgs['ItemID'] = k['ItemID']
    
        # If the Item is not active, we don't want it - Prevents sending extra API resquests for data we don't want
        if(k['SellingStatus']['ListingStatus'] != 'Active'):
            continue
        
        res['apiResponse'][k['ItemID']] = api.execute('GetItem', itemArgs).dict()
        
        # We want the error code to only be changed on the first successful iteration
        if res['error']['code'] == None:
            res['error']['code'] = '0'
    
    # After the loop is complete, return the whole res
    return res

# Use the modTime range and only return data for items that have been modified in the timerange
# Args we want are the modTime and NewItemFilter=True to get only items that have changed in this timerange
def checkRevisedItems(api=None, itemArgs=None, dateRange=None):
    # api is the connection to the Trading API
    # itemList is a list containing itemIDs to check for updates
    # itemArgs is an optional dict that contains extra details to refine the search returned by ebay 
    res = { 'error': { 'code': None, 'msg': None, 'fnc': 'checkRevisedItems' }, 'apiResponse': { 'itemIDs': [] } }
    if api == None:
        res['error']['code'] = '1'
        res['error']['msg'] = 'api is not set'
        return res
    if (itemArgs == None) | (isinstance(itemArgs, dict) != True):
        res['error']['code'] = '2'
        res['error']['msg'] = 'itemArgs doesn\'t exist or is of wrong type, must be dict'
        return res
    if (dateRange == None) | (isinstance(dateRange, dict) != True):
        dateRange = setDateRange()

    itemArgs['NewItemFilter'] = 'True'

    # Switch statement to select the proper dateRange
    itemArgs = switchDateRange(itemArgs, dateRange)
    response = api.execute('GetSellerEvents', itemArgs).dict()

    try:    
        items = response['ItemArray']['Item']

        # Store the ItemIDs that need to be updated again with getItem
        for i in items:
            res['apiResponse']['itemIDs'].append(i['ItemID'])
    except TypeError:
        res['apiResponse'] = {'code': '1', 'msg': 'No items were revised in the selected dateRange'}

    response = None

    # No Errors found
    if res['error']['code'] == None:
        res['error']['code'] = '0'
    
    return res

    
# storeItems uses the dict of Items provided by getItems and stores the information we want 
def storeItems(itemList=None):
    # itemList is the apiRequest value presented as a result of getItems 
    #   - This contains every item that matches getItems criteria with the ItemID as the key of further dicts

    # Set our error conditions
    res = { 'error': { 'code': None, 'msg': None, 'fnc': 'storeItems' }, 'apiResponse': {} }
    if (itemList == None) | (isinstance(itemList, dict) != True):
        res['error']['code'] = '2'
        res['error']['msg'] = 'itemList doesn\'t exist or is of wrong type, must be dict'
        return res
    
    # Now that we've stored all the data in a really big dictionary, lets pull only the information we want out of it
    for k in itemList:
        res['apiResponse'][k] = { 'price': {}, 'condition': {}, 'quantity': {} }
        condition = '0'
        
        # Switch statement - Sets condition.msg based on conditionID - based on table from http://developer.ebay.com/devzone/finding/callref/Enums/conditionIdList.html
        def conCheck(condition):
            # Cast the condition to a string
            condition = str(condition)
            switch = {
                '1000': 'New',
                '1500': 'New Other',
                '1750': 'New with defects',
                '2000': 'Manufacturer Refurbished',
                '2500': 'Seller Refurbished',
                '3000': 'Used',
                '4000': 'Used/Very Good Condition',
                '5000': 'Used/Good Condition',
                '6000': 'Used/Acceptable Condition',
                '7000': 'For Parts/Not Working'
            }
            # Return the approiate text or N/A if no ID matches
            return switch.get(condition, 'N/A')
        
        res['apiResponse'][k]['title'] = itemList[k]['Item']['Title']
        
        if 'ConditionID' in itemList[k]['Item']:
            # Override the condition defined at the start of the loop
            condition = itemList[k]['Item']['ConditionID']
        
        if 'SellingStatus' in itemList[k]['Item']:
            # Store current price + currency the price is in
            res['apiResponse'][k]['price']['cur'] = itemList[k]['Item']['SellingStatus']['CurrentPrice']['_currencyID']
            res['apiResponse'][k]['price']['val'] = itemList[k]['Item']['SellingStatus']['CurrentPrice']['value']
            
            # Store the quantity - Subtract sold from total to get current value
            res['apiResponse'][k]['quantity']['sold'] = itemList[k]['Item']['SellingStatus']['QuantitySold']
            res['apiResponse'][k]['quantity']['total'] = itemList[k]['Item']['Quantity']
        else:
            res['apiRequest'][k]['price']['cur'] = None
            res['apiRequest'][k]['price']['val'] = None
            res['apiRequest'][k]['quantity']['sold'] = None
            res['apiRequest'][k]['quantity']['total'] = None
        
        # Get the item specifics - Special fields pertaining to the item, such as manufacturer and part number
        if 'ItemSpecifics' in itemList[k]['Item']:
            # Try to for loop our data, if that fails, assume it's a dict with only one ItemSpecific
            try:
                for i in itemList[k]['Item']['ItemSpecifics']['NameValueList']:
                    name = i['Name']
                    if(name == 'Brand'):
                        res['apiResponse'][k]['mfg'] = i['Value']
                    if(name == 'MPN'):
                        res['apiResponse'][k]['mpn'] = i['Value']
            except TypeError:
                if itemList[k]['Item']['ItemSpecifics']['NameValueList']['Name'] == 'Brand':
                    res['apiResponse'][k]['mfg'] = itemList[k]['Item']['ItemSpecifics']['NameValueList']['Value']
                    res['apiResponse'][k]['mpn'] = None
                elif itemList[k]['Item']['ItemSpecifics']['NameValueList']['Name'] == 'MPN':
                    res['apiResponse'][k]['mpn'] = itemList[k]['Item']['ItemSpecifics']['NameValueList']['Value']
                    res['apiResponse'][k]['mfg'] = None
                else:
                    res['apiResponse'][k]['mpn'] = None
                    res['apiResponse'][k]['mfg'] = None
                    
        # Store the condition
        res['apiResponse'][k]['condition']['code'] = condition
        res['apiResponse'][k]['condition']['msg'] = conCheck(condition)
                
        # We want the error code to only be changed on the first successful iteration
        if res['error']['code'] == None:
            res['error']['code'] = '0'

    # After the loop is complete, return the whole res
    return res

# Glue logic to run all the functions above properly
def glue(api=None, sellerList=None, dateRange=None):
    # api is the connection to the api, this is passed to the functions as called
    # sellerList is the options that you can present ebay for searching (http://developer.ebay.com/DevZone/XML/docs/Reference/ebay/GetSellerEvents.html)
    # dateRange overrides EndTimeFrom and EndTimeTo from sellerList for ease of passing these required data with nothing else

    # Set our error conditions
    res = { 'error': { 'code': '0', 'msg': None, 'fnc': 'glue' }, 'apiResponse': {} }
    if api == None:
        res['error']['code'] = '1'
        res['error']['msg'] = 'api is not set'
        return res
    if (sellerList == None) | (isinstance(sellerList, dict) != True):
        res['error']['code'] = '2'
        res['error']['msg'] = 'itemList doesn\'t exist or is of wrong type, must be dict'
        return res
    if (dateRange == None) | (isinstance(dateRange, dict) != True):
        dateRange = setDateRange()

    # Switch statement to select the proper dateRange
    sellerList = switchDateRange(sellerList, dateRange)
    
    seller = getSeller(api, sellerList)
    if seller['error']['code'] == '0':
        sellerList = seller['apiResponse']
        seller = None # Unset any data we no-longer need - Saves on memory
            
        items = getItems(api, sellerList)
        if items['error']['code'] == '0':
            sellerList = items['apiResponse']
            
            
            items = storeItems(sellerList)
            storedItems = items['apiResponse']
            items = None
            
            return storedItems
        else:
            res['error'] = items['error']
            return res
    else:
        res['error'] = seller['error']
        return res


try:
    p = Parallel()

    api = Trading(domain=domain, appid=app_id, devid=dev_id, certid=crt_id, token=usr_token, config_file=None, debug=False, parellel=p)

    # Example usage, returns a dict containing all items of interst (based on the functions above)
    itemData = glue(api=api, sellerList={}, dateRange=setDateRange())
    itemlist = []

    # Write a CSV file containing some of the data we're interested in
    with open(csv_path, 'wb') as csvfile:
        Part Number Manufacturer    Condition   Price   Quantity    Description
        fieldnames = ['Part Number', 'Manufacturer', 'Condition', 'Price', 'Quantity', 'Description']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=csv_delimiter, quotechar=csv_quote, quoting=csv.QUOTE_MINIMAL)

        for i in itemData:
            data = {
                'Part Number': i['mpn'],
                'Manufacturer': i['mfg'],
                'Condition': i['condition']['msg'],
                'Price': i['price']['val']+' '+i['price']['cur'],
                'Quantity': str(int(i['quantity']['total'])-int(i['quantity']['sold'])),
                'Description': i['title']
            }

            writer.writerow(data)

            # Store the itemIDs so that we can use them to check which ones were modified
            itemlist.append(i)

except ConnectionError as e:
    print(e)