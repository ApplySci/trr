# -*- coding: utf-8 -*-
"""
This does all the comms with, & handling of, the google scoresheet
"""

from datetime import datetime, timedelta
import os
import logging

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


def setup_logging():
    """Configure logging to write to both file and console"""
    # Clear the log file
    with open("import.log", "w", encoding="utf-8") as f:
        f.write("")

    # Set up logging
    logger = logging.getLogger("GSP")
    logger.setLevel(logging.DEBUG)

    # Remove any existing handlers
    logger.handlers = []

    # File handler with UTF-8 encoding
    file_handler = logging.FileHandler("import.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)

    # Console handler with UTF-8 encoding
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)

    # Format
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


class GSP:
    def __init__(self, id: str) -> None:
        self.logger = setup_logging()
        self.creds = ServiceAccountCredentials.from_json_keyfile_name(KEYFILE, SCOPE)
        self.client = gspread.authorize(self.creds)
        self.sheet = self.client.open_by_key(id)
        self.engine = create_engine("sqlite:///mahjong.db")
        Base.metadata.drop_all(self.engine)
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

    def convert_country_code(self, code: str) -> str:
        """Convert special country codes to their standard form"""
        if not code:
            return code

        conversions = {
            "BAR": "BRB",  # Barbados
            "GBWL": "GBR",  # Great Britain (Wales). Lauren!
            "ISV": "VIR",  # US Virgin Islands
            "IVB": "VGB",  # British Virgin Islands
            "MAS": "MYS",  # Malaysia
            "NGR": "NGA",  # Nigeria
            "NIG": "NER",  # Niger
            "ROC": "TWN",  # Taiwan
            "XXX": "",  # None
        }

        return conversions.get(code, code)

    def _import_countries(self, session: Session) -> Dict[str, Country]:
        """Import countries and return dict mapping 3-letter code to Country object"""
        countries_ws = self.sheet.worksheet("Countries")
        countries_data = countries_ws.get_all_records()
        countries_dict = {}

        # Track seen country IDs for debugging
        seen_country_ids = {}

        for row in countries_data:
            code_3 = row["Code"]

            # Skip 4-letter codes and TAU
            if len(code_3) > 3 or code_3 == "TAU" or code_3 == "XXX":
                continue

            name = row["Name"]
            old_code_3 = code_3
            code_3 = self.convert_country_code(code_3)

            country_obj = None
            try_code = True

            # Try matching by name first, unless we've already caught a weird code and fixed it
            try:
                if old_code_3 == code_3:
                    country_obj = pycountry.countries.search_fuzzy(name)[0]
                    try_code = False
            except LookupError:
                pass

            if try_code:
                # Fall back to code lookup
                country_obj = pycountry.countries.get(alpha_3=code_3)
                if not country_obj:
                    self.logger.warning(
                        f"Could not find country by name: {name} or code: {code_3}"
                    )
                    continue

            # Debug logging for duplicate detection
            if country_obj.alpha_2 in seen_country_ids:
                prev_entry = seen_country_ids[country_obj.alpha_2]
                self.logger.error(
                    f"""Duplicate country ID detected:
                    Previous entry: id={country_obj.alpha_2}, code_3={prev_entry['code_3']}, name={prev_entry['name']}
                    Current entry: id={country_obj.alpha_2}, code_3={code_3}, name={name}"""
                )
                continue

            seen_country_ids[country_obj.alpha_2] = {"code_3": code_3, "name": name}

            country = Country(id=country_obj.alpha_2, code_3=code_3, name_english=name)
            session.add(country)
            countries_dict[code_3] = country

        session.flush()
        return countries_dict

    def _import_clubs(self, session: Session) -> None:
        clubs_ws = self.sheet.worksheet("Clubs")
        clubs_data = clubs_ws.get_all_records(value_render_option="FORMATTED_VALUE")

        for row in clubs_data:
            # Skip if code is empty, explicitly convert to string
            code = str(row["Code"]).strip() if row["Code"] else ""
            if not code:
                continue

            country = session.query(Country).filter_by(code_3=row["Nat"]).first()
            if not country:
                continue

            club = Club(
                id=row["ID"],
                code=code,  # Use the converted string value
                country_id=country.id,
                town_region=row["Town/Region"],
            )
            session.add(club)

    def _find_column(self, row: dict, variations: List[str]) -> str:
        """Helper function to find the correct column name from possible variations"""
        for var in variations:
            if var in row:
                return var
        print("Available columns:", list(row.keys()))
        raise KeyError(f"Could not find column. Tried: {variations}")

    def _import_players(self, session: Session) -> Dict[str, Player]:
        """Import players and return dict mapping TRR ID to Player object"""
        players_ws = self.sheet.worksheet("Players")
        players_data = players_ws.get_all_records(value_render_option="FORMATTED_VALUE")

        # Find correct column names
        first_row = players_data[0]
        trr_id_col = self._find_column(first_row, ["ID TRR", "ID\nTRR", "IDTRR"])
        ema_id_col = self._find_column(first_row, ["ID EMA", "ID\nEMA", "IDEMA"])
        ema_nat_col = self._find_column(
            first_row, ["EMA Nat", "EMA\nNat", "EMANAT", "EMA NAT"]
        )
        club_col = self._find_column(
            first_row, ["CLUB Short", "CLUB\nShort", "CLUBShort"]
        )

        # Track seen EMA IDs
        seen_ema_ids = {}

        players_dict = {}
        for row in players_data:
            trr_id = str(row[trr_id_col]).strip()
            # Skip if TRR ID is empty
            if not trr_id:
                continue

            country_code = str(row[ema_nat_col]).strip() if row[ema_nat_col] else None

            # Handle special country codes
            if country_code:
                if country_code == "XXX":
                    country_code = None
                else:
                    country_code = self.convert_country_code(country_code)
                    if len(country_code) > 3:
                        self.logger.warning(
                            f"Player {trr_id} has invalid country code: {country_code} (more than 3 letters)"
                        )

            club_code = str(row[club_col]).strip() if row[club_col] else None
            ema_id = str(row[ema_id_col]).strip() if row[ema_id_col] else None

            # Try to find country, allow it to be None
            country = None
            if country_code:
                country = session.query(Country).filter_by(code_3=country_code).first()
                if not country:
                    self.logger.warning(
                        f"Could not find country '{country_code}' in database"
                    )

            # Try to find club, allow it to be None
            club = None
            if club_code and club_code != "XXX":
                club = session.query(Club).filter_by(code=club_code).first()
                if not club:
                    # Try to find country for the new club
                    if country:  # Use the player's country
                        # Create a new club
                        club = Club(
                            code=club_code,
                            country_id=country.id,
                            town_region=f"{club_code} - {country.name_english}"
                        )
                        session.add(club)
                        session.flush()  # Get club.id
                        self.logger.warning(
                            f"Created missing club: {club_code} in {country.name_english}"
                        )
                    else:
                        self.logger.warning(
                            f"Could not create club '{club_code}' - no country found for player"
                        )

            # Handle duplicate EMA IDs
            if ema_id:
                if ema_id in seen_ema_ids:
                    self.logger.warning(
                        f"Duplicate EMA ID found: {ema_id} for player {trr_id}"
                    )
                    # Append ??? to both the original and current EMA ID
                    original_player = seen_ema_ids[ema_id]
                    original_player.ema_id = f"{original_player.ema_id}???"
                    ema_id = f"{ema_id}???"
                else:
                    seen_ema_ids[ema_id] = player

            player = Player(
                name=f"{row['FIRST NAME']} {row['LAST NAME']}",
                trr_id=trr_id,
                ema_id=ema_id,
                club_id=club.id if club else None,
                country_id=country.id if country else None,
            )
            session.add(player)
            players_dict[trr_id] = player

        # Add explicit commit here
        session.commit()

        return players_dict

    def _import_tournaments(self, session: Session) -> Dict[str, Tournament]:
        """Import tournaments and return dict mapping tournament ID to Tournament object"""
        tournaments_ws = self.sheet.worksheet("Tournaments")

        # Get all values as a list of lists instead of using get_all_records
        all_values = tournaments_ws.get_all_values()
        headers = all_values[1]  # Use row 2 as headers
        tournaments_data = []

        # Convert to list of dicts manually
        for row in all_values[2:]:  # Skip header rows
            row_dict = {}
            for i, value in enumerate(row):
                if i < len(headers):  # Ensure we don't go past header length
                    row_dict[headers[i]] = value
            tournaments_data.append(row_dict)

        tournaments_dict = {}
        for row in tournaments_data:
            host_nation = row.get("Host\nNation") or row.get("Host Nation")
            country = session.query(Country).filter_by(code_3=host_nation).first()
            if not country:
                self.logger.warning(
                    f"Could not find country for tournament {row['ID']}"
                )
                continue

            tournament = Tournament(
                id=row["ID"],
                first_day=datetime.strptime(row["First Day"], "%Y-%m-%d").date(),
                country_id=country.id,
                town=row["Town"],
                rules=row["Rules"],
                name=row["Name"],
                status=row.get("Status", "")
            )
            session.add(tournament)
            tournaments_dict[row["ID"]] = tournament

        session.flush()
        return tournaments_dict

    def _find_tournament(
        self, session: Session, game_date: datetime.date, town: str
    ) -> Optional[Tournament]:
        """Find tournament based on date and town. Returns None if no match found."""
        # Get tournaments that start within 5 days before the game date
        potential_tournaments = (
            session.query(Tournament)
            .filter(
                Tournament.first_day <= game_date,
                Tournament.first_day >= game_date - timedelta(days=5),
                Tournament.town == town,
            )
            .all()
        )

        if len(potential_tournaments) == 0:
            return None
        elif len(potential_tournaments) > 1:
            self.logger.error(
                f"Multiple tournaments found for game in {town} on {game_date}"
            )
            return potential_tournaments[0]  # Use first match

        return potential_tournaments[0]

    def _find_club(self, session: Session, town: str) -> Optional[Club]:
        """Find club based on town. Returns None if no match found."""
        club = session.query(Club).filter(Club.town_region.ilike(f"%{town}%")).first()
        return club

    def _import_games(self, session: Session) -> None:
        """Import games and player_game associations"""
        games_ws = self.sheet.worksheet("Games")

        # Get all values as a list of lists
        all_values = games_ws.get_all_values()
        games_data = []

        # Convert to list of dicts manually, handling the player columns specially
        for row in all_values[2:]:  # Skip header rows
            if len(row) < 13:  # Ensure minimum required columns
                continue

            game_dict = {"Date": row[0], "Town": row[1], "Table": row[3], "Players": []}

            # Process player data in pairs of ID and Result
            for i in range(4, 12, 2):
                if i + 1 < len(row) and row[i].strip():  # Only add if ID is not empty
                    game_dict["Players"].append(
                        {
                            "ID": row[
                                i
                            ].strip(),  # Add strip() to remove any whitespace
                            "Result": row[i + 1],
                        }
                    )

            games_data.append(game_dict)

        for row in games_data:
            # Get all players by their TRR IDs and scores
            players = []
            scores = []

            for player_data in row["Players"]:
                player = (
                    session.query(Player)
                    .filter(Player.trr_id == player_data["ID"])
                    .first()
                )
                if not player:
                    self.logger.error(
                        f"Warning: Could not find player with TRR ID '{player_data['ID']}' for game"
                    )
                    all_trr_ids = session.query(Player.trr_id).all()
                    self.logger.error(
                        f"Available TRR IDs in database: {[id[0] for id in all_trr_ids]}"
                    )
                    return
                players.append(player)
                scores.append(
                    int(player_data["Result"]) if player_data["Result"] else 0
                )

            if len(players) != 4:
                self.logger.error(f"Skipping game due to missing players")
                break

            # Find tournament based on date and town
            game_date = datetime.strptime(row["Date"], "%Y-%m-%d").date()
            tournament = self._find_tournament(session, game_date, row["Town"])

            # Initialize game attributes
            game_attrs = {
                "p1": players[0].id,
                "p2": players[1].id,
                "p3": players[2].id,
                "p4": players[3].id,
                "round": "1",  # Default to round 1 since we don't have this info
                "table": str(row["Table"]),
                "date": game_date,
            }

            if tournament:
                # It's a tournament game
                game_attrs.update(
                    {
                        "is_tournament": True,
                        "tournament_id": tournament.id,
                        "club_id": None,
                    }
                )
            else:
                # Try to find a club match
                club = self._find_club(session, row["Town"])
                if club:
                    game_attrs.update(
                        {
                            "is_tournament": False,
                            "tournament_id": None,
                            "club_id": club.id,
                        }
                    )
                else:
                    self.logger.error(
                        f"Could not find tournament or club for game in {row['Town']} on {game_date}"
                    )
                    continue

            game = Game(**game_attrs)
            session.add(game)
            session.flush()  # Get game.id

            # Create player_game associations with scores
            seen_players = set()  # Track players we've already processed for this game
            for player, score in zip(players, scores):
                # Check for duplicate players in the same game
                if player.id in seen_players:
                    self.logger.error(
                        f"""Duplicate player in game:
                        Game ID: {game.id}
                        Tournament: {tournament.name} ({tournament.id})
                        Date: {game_date}
                        Player: {player.name} (ID: {player.id}, TRR ID: {player.trr_id})
                        Scores: {scores}
                        All players: {[(p.name, p.id, p.trr_id) for p in players]}"""
                    )
                    continue

                seen_players.add(player.id)

                try:
                    stmt = player_game.insert().values(
                        player_id=player.id, game_id=game.id, score=score
                    )
                    session.execute(stmt)
                except Exception as e:
                    self.logger.error(
                        f"""Error inserting player-game association:
                        Game ID: {game.id}
                        Tournament: {tournament.name} ({tournament.id})
                        Date: {game_date}
                        Player: {player.name} (ID: {player.id}, TRR ID: {player.trr_id})
                        Score: {score}
                        Error: {str(e)}"""
                    )
                    raise  # Re-raise the exception after logging


if __name__ == "__main__":
    from config import SHEET_ID

    gs = GSP(SHEET_ID)
    gs.import_data()
