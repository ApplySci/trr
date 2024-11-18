from collections.abc import Sequence
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from models import Game, player_game, RatingModel
from openskill.models import PlackettLuce, BradleyTerryPart, ThurstoneMostellerPart


class RatingCalculator:
    def __init__(self, model_type: RatingModel):
        self.engine = create_engine("sqlite:///mahjong.db")
        self.model = self._get_model(model_type)
        self.players: dict[int, any] = {}  # player_id -> rating

    def _get_model(self, model_type: RatingModel) -> any:
        """Initialize the specified rating model"""
        if model_type == RatingModel.PLACKETT_LUCE:
            return PlackettLuce()
        elif model_type == RatingModel.BRADLEY_TERRY:
            return BradleyTerryPart()
        elif model_type == RatingModel.THURSTONE_MOSTELLER:
            return ThurstoneMostellerPart()
        else:
            raise ValueError(f"Unknown model type: {model_type}")

    def _get_or_create_rating(self, player_id: int) -> any:
        """Get existing rating or create new one for player"""
        if player_id not in self.players:
            self.players[player_id] = self.model.rating(name=str(player_id))
        return self.players[player_id]

    def process_game(self, game: Game, scores: list[tuple[int, int]]) -> None:
        """Process a single game's results"""
        # Sort players and scores by player position (p1, p2, p3, p4)
        player_ids = [game.p1, game.p2, game.p3, game.p4]

        # Get ratings for each player
        ratings = [self._get_or_create_rating(pid) for pid in player_ids]

        # Format match data for OpenSkill
        match = [[r] for r in ratings]
        scores = [score for _, score in scores]

        # Update ratings
        updated_ratings = self.model.rate(match, scores=scores)

        # Store updated ratings
        for pid, [rating] in zip(player_ids, updated_ratings):
            self.players[pid] = rating

    def calculate_ratings(self) -> list[tuple[int, float]]:
        """Calculate ratings for all players based on game history"""
        with Session(self.engine) as session:
            # Get all games and their scores
            games = session.query(Game).all()

            for game in games:
                # Get scores for this game
                scores = (
                    session.query(player_game.c.player_id, player_game.c.score)
                    .filter(player_game.c.game_id == game.id)
                    .all()
                )

                self.process_game(game, scores)

        # Convert final ratings to list of (player_id, rating) tuples
        return [(int(r.name), r.ordinal()) for r in self.players.values()]


def get_player_rankings(model_type: RatingModel) -> list[tuple[int, float]]:
    """Main function to get player rankings using specified model"""
    calculator = RatingCalculator(model_type)
    rankings = calculator.calculate_ratings()
    return sorted(rankings, key=lambda x: x[1], reverse=True)


if __name__ == "__main__":
    # Example usage
    rankings = get_player_rankings(RatingModel.BRADLEY_TERRY)
    for player_id, rating in rankings:
        print(f"Player {player_id}: {rating}")
