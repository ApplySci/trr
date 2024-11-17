# -*- coding: utf-8 -*-
"""
This does all the comms with, & handling of, the google scoresheet
"""

from datetime import datetime
import os

import gspread
from gspread.exceptions import APIError as GspreadAPIError
from oauth2client.service_account import ServiceAccountCredentials
from zoneinfo import ZoneInfo


SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

app_directory = os.path.dirname(os.path.realpath(__file__))
KEYFILE = os.path.join(app_directory, "fcm-admin.json")

class GSP:
    def __init__(self, id: str) -> None:
        self.creds = ServiceAccountCredentials.from_json_keyfile_name(KEYFILE, SCOPE)
        self.client = gspread.authorize(self.creds)
        self.sheet = self.client.open_by_key(id)


if __name__ == "__main__":
    from config import SHEET_ID
    gs = GSP(SHEET_ID)
    vals = gs.sheet.worksheet("Players").get(
        value_render_option=gspread.utils.ValueRenderOption.unformatted
        )[0:2]
    print(vals)
