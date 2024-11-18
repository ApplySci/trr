from sqlalchemy import Column, Date, Enum, ForeignKey, Integer, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import String
from sqlalchemy.ext.hybrid import hybrid_property
from typing import List, Optional


class Base(DeclarativeBase):
    pass


# Association table for Player-Game many-to-many relationship
player_game = Table(
    "player_game",
    Base.metadata,
    Column("player_id", Integer, ForeignKey("player.id"), primary_key=True),
    Column("game_id", Integer, ForeignKey("game.id"), primary_key=True),
    Column("score", Integer, nullable=False),
)


class Player(Base):
    __tablename__ = "player"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String)
    trr_id: Mapped[str] = mapped_column(String, unique=True)
    ema_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    club_id: Mapped[Optional[int]] = mapped_column(ForeignKey("club.id"), nullable=True)
    country_id: Mapped[Optional[str]] = mapped_column(ForeignKey("country.id"), nullable=True)

    # Relationships
    club: Mapped[Optional["Club"]] = relationship("Club", back_populates="players")
    country: Mapped[Optional["Country"]] = relationship("Country", back_populates="players")
    games: Mapped[List["Game"]] = relationship(
        "Game", secondary=player_game, back_populates="players"
    )
    tournaments: Mapped[List["Tournament"]] = relationship(
        "Tournament", secondary="tournament_player", back_populates="players"
    )


class Game(Base):
    __tablename__ = "game"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    p1: Mapped[int] = mapped_column(ForeignKey("player.id"))
    p2: Mapped[int] = mapped_column(ForeignKey("player.id"))
    p3: Mapped[int] = mapped_column(ForeignKey("player.id"))
    p4: Mapped[int] = mapped_column(ForeignKey("player.id"))
    round: Mapped[str] = mapped_column(String)
    table: Mapped[str] = mapped_column(String)
    date: Mapped[Date] = mapped_column(Date)
    is_tournament: Mapped[bool] = mapped_column(default=True)
    tournament_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tournament.id"), nullable=True)
    club_id: Mapped[Optional[int]] = mapped_column(ForeignKey("club.id"), nullable=True)

    # Relationships
    tournament: Mapped[Optional["Tournament"]] = relationship(
        "Tournament", back_populates="games"
    )
    club: Mapped[Optional["Club"]] = relationship(
        "Club", back_populates="games"
    )
    players: Mapped[List["Player"]] = relationship(
        "Player", secondary=player_game, back_populates="games"
    )


class Tournament(Base):
    __tablename__ = "tournament"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    first_day: Mapped[Date] = mapped_column(Date)
    country_id: Mapped[str] = mapped_column(ForeignKey("country.id"))
    town: Mapped[str] = mapped_column(String)
    rules: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)

    # Relationships
    country: Mapped["Country"] = relationship("Country", back_populates="tournaments")
    games: Mapped[List["Game"]] = relationship("Game", back_populates="tournament")
    players: Mapped[List["Player"]] = relationship(
        "Player", secondary="tournament_player", back_populates="tournaments"
    )


# Association table for Tournament-Player many-to-many relationship
tournament_player = Table(
    "tournament_player",
    Base.metadata,
    Column("tournament_id", Integer, ForeignKey("tournament.id"), primary_key=True),
    Column("player_id", Integer, ForeignKey("player.id"), primary_key=True),
)


class Club(Base):
    __tablename__ = "club"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[str] = mapped_column(ForeignKey("country.id"))
    code: Mapped[str] = mapped_column(String)
    town_region: Mapped[str] = mapped_column(String)

    # Relationships
    country: Mapped["Country"] = relationship("Country", back_populates="clubs")
    players: Mapped[List["Player"]] = relationship("Player", back_populates="club")
    games: Mapped[List["Game"]] = relationship("Game", back_populates="club")


class Country(Base):
    __tablename__ = "country"

    id: Mapped[str] = mapped_column(String(2), primary_key=True)
    code_3: Mapped[str] = mapped_column(String(3))
    name_english: Mapped[str] = mapped_column(String)

    # Relationships
    clubs: Mapped[List["Club"]] = relationship("Club", back_populates="country")
    players: Mapped[List["Player"]] = relationship("Player", back_populates="country")
    tournaments: Mapped[List["Tournament"]] = relationship(
        "Tournament", back_populates="country"
    )
