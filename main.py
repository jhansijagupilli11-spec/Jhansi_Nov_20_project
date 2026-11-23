"""Flight Ticket Booking """
import os
import random
import string
from datetime import date, datetime, time, timedelta
from typing import List, Optional
from urllib.parse import quote_plus

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (Column, Date, DateTime, ForeignKey, Integer, Numeric,
                        String, Time, create_engine, func)
from sqlalchemy.orm import (Session, declarative_base, joinedload,
                            relationship, sessionmaker)

# =====================================================================
# 1. DATABASE CONNECTION
# =====================================================================
load_dotenv()  # reads the .env file in this folder

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "12345")
DB_NAME = os.getenv("DB_NAME", "flight_booking")

# Optional: set DATABASE_URL to use another database (e.g. sqlite:///test.db for a quick test)
DATABASE_URL = os.getenv("DATABASE_URL") or (
    f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """Gives each request its own DB session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =====================================================================
# 2. DATABASE TABLES
# =====================================================================
class Flight(Base):
    __tablename__ = "flights"

    id = Column(Integer, primary_key=True, index=True)
    flight_number = Column(String(10), nullable=False)
    airline = Column(String(50), nullable=False)
    source = Column(String(50), nullable=False, index=True)
    destination = Column(String(50), nullable=False, index=True)
    departure_date = Column(Date, nullable=False, index=True)
    departure_time = Column(Time, nullable=False)
    arrival_time = Column(Time, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)  # price per passenger
    total_seats = Column(Integer, nullable=False, default=60)
    available_seats = Column(Integer, nullable=False, default=60)


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    booking_ref = Column(String(10), unique=True, nullable=False, index=True)  # e.g. FBK7X2QP
    flight_id = Column(Integer, ForeignKey("flights.id"), nullable=False)
    contact_email = Column(String(120), nullable=False, index=True)
    contact_phone = Column(String(20), nullable=False)
    total_price = Column(Numeric(10, 2), nullable=False)
    status = Column(String(15), nullable=False, default="CONFIRMED")  # CONFIRMED / CANCELLED
    created_at = Column(DateTime, server_default=func.now())

    flight = relationship("Flight")
    passengers = relationship("Passenger", back_populates="booking",
                              cascade="all, delete-orphan")


class Passenger(Base):
    __tablename__ = "passengers"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    name = Column(String(100), nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String(10), nullable=False)

    booking = relationship("Booking", back_populates="passengers")


# =====================================================================
# 3. SCHEMAS (validate the JSON going in and out of the API)
# =====================================================================
class FlightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    flight_number: str
    airline: str
    source: str
    destination: str
    departure_date: date
    departure_time: time
    arrival_time: time
    price: float
    available_seats: int


class PassengerIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    age: int = Field(ge=0, le=120)
    gender: str = Field(pattern="^(Male|Female|Other)$")


class PassengerOut(PassengerIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class BookingCreate(BaseModel):
    flight_id: int
    contact_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    contact_phone: str = Field(min_length=7, max_length=20)
    passengers: List[PassengerIn] = Field(min_length=1, max_length=9)


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    booking_ref: str
    status: str
    contact_email: str
    contact_phone: str
    total_price: float
    created_at: Optional[datetime] = None
    flight: FlightOut
    passengers: List[PassengerOut]


# =====================================================================
# 4. SAMPLE DATA (added automatically the first time the server starts)
# =====================================================================
# (city A, city B, flight time in minutes, base price in rupees)
ROUTES = [
    ("Delhi", "Mumbai", 130, 5500), ("Delhi", "Bangalore", 170, 6500),
    ("Delhi", "Chennai", 175, 6800), ("Delhi", "Kolkata", 135, 5200),
    ("Delhi", "Hyderabad", 140, 5600), ("Mumbai", "Bangalore", 100, 4200),
    ("Mumbai", "Chennai", 115, 4500), ("Mumbai", "Hyderabad", 95, 3900),
    ("Mumbai", "Kolkata", 160, 6000), ("Bangalore", "Chennai", 60, 2600),
    ("Bangalore", "Hyderabad", 75, 3000), ("Bangalore", "Kolkata", 150, 5800),
    ("Chennai", "Hyderabad", 80, 3100), ("Chennai", "Kolkata", 125, 4900),
    ("Hyderabad", "Kolkata", 125, 4700),
]

# (departure time, airline, airline code)
SLOTS = [("06:30", "IndiGo", "6E"), ("13:15", "Air India", "AI"), ("19:45", "SpiceJet", "SG")]

DAYS_AHEAD = 45


def seed_flights(db: Session):
    """Add sample flights for the next 45 days, but only if the flights table is empty."""
    if db.query(Flight).count() > 0:
        return

    random.seed(42)
    today = date.today()
    flights = []

    for city_a, city_b, minutes, base_price in ROUTES:
        for source, destination in ((city_a, city_b), (city_b, city_a)):  # both directions
            for day in range(DAYS_AHEAD):
                travel_date = today + timedelta(days=day)
                for dep_str, airline, code in SLOTS:
                    dep = datetime.strptime(dep_str, "%H:%M")
                    arr = dep + timedelta(minutes=minutes)
                    seats = random.randint(30, 60)
                    flights.append(Flight(
                        flight_number=f"{code}{random.randint(100, 999)}",
                        airline=airline,
                        source=source,
                        destination=destination,
                        departure_date=travel_date,
                        departure_time=dep.time(),
                        arrival_time=arr.time(),
                        price=round(base_price * random.uniform(0.85, 1.25), -1),
                        total_seats=seats,
                        available_seats=seats,
                    ))

    db.add_all(flights)
    db.commit()
    print(f"Added {len(flights)} sample flights.")


# Create the tables if they don't exist yet, then add sample flights on first run.
Base.metadata.create_all(bind=engine)
with SessionLocal() as _session:
    seed_flights(_session)


# =====================================================================
# 5. API ENDPOINTS
# =====================================================================
app = FastAPI(title="Flight Ticket Booking API")

# Allow the React app (port 5173) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def generate_booking_ref(db: Session) -> str:
    """Make a unique reference like FBK7X2QP."""
    while True:
        ref = "FB" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not db.query(Booking).filter(Booking.booking_ref == ref).first():
            return ref


# ---------------------------------------------------------------- Flights
@app.get("/api/cities", response_model=List[str])
def list_cities(db: Session = Depends(get_db)):
    """All cities we fly from (used for the dropdowns)."""
    rows = db.query(Flight.source).distinct().order_by(Flight.source).all()
    return [row[0] for row in rows]


@app.get("/api/flights", response_model=List[FlightOut])
def search_flights(source: str, destination: str, travel_date: date,
                   passengers: int = 1, db: Session = Depends(get_db)):
    """Search flights by source, destination and travel date."""
    if source.lower() == destination.lower():
        raise HTTPException(400, "Source and destination must be different")
    if travel_date < date.today():
        raise HTTPException(400, "Travel date cannot be in the past")

    return (
        db.query(Flight)
        .filter(
            Flight.source == source,
            Flight.destination == destination,
            Flight.departure_date == travel_date,
            Flight.available_seats >= passengers,
        )
        .order_by(Flight.departure_time)
        .all()
    )


# ---------------------------------------------------------------- Bookings
@app.post("/api/bookings", response_model=BookingOut, status_code=201)
def create_booking(data: BookingCreate, db: Session = Depends(get_db)):
    """Book a flight for one or more passengers."""
    # Lock the flight row so two people can't book the last seat at the same time.
    flight = db.query(Flight).filter(Flight.id == data.flight_id).with_for_update().first()
    if not flight:
        raise HTTPException(404, "Flight not found")
    if flight.departure_date < date.today():
        raise HTTPException(400, "This flight has already departed")

    count = len(data.passengers)
    if flight.available_seats < count:
        raise HTTPException(400, f"Only {flight.available_seats} seat(s) left on this flight")

    flight.available_seats -= count

    booking = Booking(
        booking_ref=generate_booking_ref(db),
        flight_id=flight.id,
        contact_email=data.contact_email.strip().lower(),
        contact_phone=data.contact_phone.strip(),
        total_price=flight.price * count,
        status="CONFIRMED",
        passengers=[
            Passenger(name=p.name.strip(), age=p.age, gender=p.gender)
            for p in data.passengers
        ],
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


@app.get("/api/bookings", response_model=List[BookingOut])
def find_bookings(email: Optional[str] = None, ref: Optional[str] = None,
                  db: Session = Depends(get_db)):
    """Find bookings by e-mail address or by booking reference."""
    if not email and not ref:
        raise HTTPException(400, "Please provide an email or a booking reference")

    query = db.query(Booking).options(joinedload(Booking.flight), joinedload(Booking.passengers))
    if ref:
        query = query.filter(Booking.booking_ref == ref.strip().upper())
    if email:
        query = query.filter(Booking.contact_email == email.strip().lower())
    return query.order_by(Booking.created_at.desc(), Booking.id.desc()).all()


@app.get("/api/bookings/{ref}", response_model=BookingOut)
def get_booking(ref: str, db: Session = Depends(get_db)):
    booking = db.query(Booking).filter(Booking.booking_ref == ref.upper()).first()
    if not booking:
        raise HTTPException(404, "Booking not found")
    return booking


@app.post("/api/bookings/{ref}/cancel", response_model=BookingOut)
def cancel_booking(ref: str, db: Session = Depends(get_db)):
    """Cancel a booking and give the seats back to the flight."""
    booking = db.query(Booking).filter(Booking.booking_ref == ref.upper()).first()
    if not booking:
        raise HTTPException(404, "Booking not found")
    if booking.status == "CANCELLED":
        raise HTTPException(400, "This booking is already cancelled")

    flight = db.query(Flight).filter(Flight.id == booking.flight_id).with_for_update().first()
    if flight.departure_date < date.today():
        raise HTTPException(400, "Past flights cannot be cancelled")

    flight.available_seats += len(booking.passengers)
    booking.status = "CANCELLED"
    db.commit()
    db.refresh(booking)
    return booking
