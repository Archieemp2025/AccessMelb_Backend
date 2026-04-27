from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer
from geoalchemy2 import Geometry
from typing import Optional



class Base(DeclarativeBase):
    pass


class Destination(Base):
    __tablename__ = "destination"

    destination_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feature_name: Mapped[str] = mapped_column(String(255))
    theme: Mapped[str] = mapped_column(String(100))
    sub_theme: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    location = mapped_column(Geometry("POINT", srid=4326))
    place_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class PublicToilet(Base):
    __tablename__ = "public_toilet"

    toilet_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    wheelchair_accessible: Mapped[str] = mapped_column(String(10))
    location = mapped_column(Geometry("POINT", srid=4326))