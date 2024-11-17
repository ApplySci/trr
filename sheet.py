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
import pycountry
from typing import Dict, List, Optional
from models import Base, Player, Game, Tournament, Country, Club, player_game
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


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
        self.engine = create_engine("sqlite:///mahjong.db")
        Base.metadata.create_all(self.engine)

    def import_data(self) -> None:
        with Session(self.engine) as session:
            # First import countries and clubs as they're referenced by other tables
            countries = self._import_countries(session)
            self._import_clubs(session)

            # Then players as they're referenced by games
            self._import_players(session)

            # Then tournaments as they're referenced by games
            self._import_tournaments(session)

            # Finally games and player_game associations
            self._import_games(session)

            session.commit()

    def _import_countries(self, session: Session) -> Dict[str, Country]:
        """Import countries and return dict mapping 3-letter code to Country object"""
        countries_ws = self.sheet.worksheet("Countries")
        countries_data = countries_ws.get_all_records()

        countries_dict = {}
        for row in countries_data:
            code_3 = row["Code"]
            # Find 2-letter code using pycountry
            country_obj = pycountry.countries.get(alpha_3=code_3)
            if not country_obj:
                print(f"Warning: Could not find country with code {code_3}")
                continue

            country = Country(
                id=country_obj.alpha_2, code_3=code_3, name_english=row["Name"]
            )
            session.add(country)
            countries_dict[code_3] = country

        session.flush()  # Ensure IDs are generated
        return countries_dict

    def _import_clubs(self, session: Session) -> None:
        clubs_ws = self.sheet.worksheet("Clubs")
        clubs_data = clubs_ws.get_all_records()

        for row in clubs_data:
            country = session.query(Country).filter_by(code_3=row["Nat"]).first()
            if not country:
                print(f"Warning: Could not find country for club {row['Code']}")
                continue

            club = Club(
                id=row["ID"], country_id=country.id, town_region=row["Town/Region"]
            )
            session.add(club)

    def _import_players(self, session: Session) -> Dict[str, Player]:
        """Import players and return dict mapping TRR ID to Player object"""
        players_ws = self.sheet.worksheet("Players")
        players_data = players_ws.get_all_records()

        players_dict = {}
        for row in players_data:
            # Get country and club
            country = session.query(Country).filter_by(code_3=row["EMA Nat"]).first()
            club = session.query(Club).filter_by(id=row["CLUB Short"]).first()

            if not country or not club:
                print(
                    f"Warning: Could not find country/club for player {row['ID TRR']}"
                )
                continue

            player = Player(
                name=f"{row['FIRST NAME']} {row['LAST NAME']}",
                trr_id=row["ID TRR"],
                ema_id=row["ID EMA"] if row["ID EMA"] else None,
                club_id=club.id,
                country_id=country.id,
            )
            session.add(player)
            players_dict[row["ID TRR"]] = player

        session.flush()
        return players_dict

    def _import_tournaments(self, session: Session) -> Dict[str, Tournament]:
        """Import tournaments and return dict mapping tournament ID to Tournament object"""
        tournaments_ws = self.sheet.worksheet("Tournaments")
        tournaments_data = tournaments_ws.get_all_records()

        tournaments_dict = {}
        for row in tournaments_data:
            if row["Status"] != "OK":
                continue

            country = (
                session.query(Country).filter_by(code_3=row["Host Nation"]).first()
            )
            if not country:
                print(f"Warning: Could not find country for tournament {row['ID']}")
                continue

            tournament = Tournament(
                id=row["ID"],
                first_day=datetime.strptime(row["First Day"], "%Y-%m-%d").date(),
                country_id=country.id,
                town=row["Town"],
                rules=row["Rules"],
                name=row["Name"],
            )
            session.add(tournament)
            tournaments_dict[row["ID"]] = tournament

        session.flush()
        return tournaments_dict

    def _import_games(self, session: Session) -> None:
        """Import games and player_game associations"""
        games_ws = self.sheet.worksheet("Games")
        games_data = games_ws.get_all_records()

        for row in games_data:
            # Get all players by their TRR IDs
            players = []
            scores = []
            for i in range(1, 5):
                player = session.query(Player).filter_by(trr_id=row[f"ID_{i}"]).first()
                if not player:
                    print(f"Warning: Could not find player {row[f'ID_{i}']} for game")
                    continue
                players.append(player)
                scores.append(row[f"Result_{i}"])

            if len(players) != 4:
                print(f"Warning: Skipping game due to missing players")
                continue

            # Find tournament
            tournament = (
                session.query(Tournament).filter_by(id=row["Tournament_ID"]).first()
            )
            if not tournament:
                print(f"Warning: Could not find tournament for game")
                continue

            game = Game(
                p1=players[0].id,
                p2=players[1].id,
                p3=players[2].id,
                p4=players[3].id,
                round=str(row["Round"]),
                table=str(row["Table"]),
                date=datetime.strptime(row["Date"], "%Y-%m-%d").date(),
                tournament_id=tournament.id,
            )
            session.add(game)
            session.flush()  # Get game.id

            # Create player_game associations with scores
            for player, score in zip(players, scores):
                stmt = player_game.insert().values(
                    player_id=player.id, game_id=game.id, score=score
                )
                session.execute(stmt)


if __name__ == "__main__":
    from config import SHEET_ID

    gs = GSP(SHEET_ID)
    vals = gs.sheet.worksheet("Players").get(
        value_render_option=gspread.utils.ValueRenderOption.unformatted
    )[0:2]
    print(vals)
