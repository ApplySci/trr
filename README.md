build an sqlite3 database of riichi tournament results 

create config.py with SHEET_ID='{the google id of the sheet you are importing}'
From google console, get an fcm_admin.json file for your service account, with your client id and private key, to allow you to use the Sheets API.

run sheet.py to import from the google sheet