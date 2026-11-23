import contextlib, itertools, random, pymysql   # Flight Booking API - FastAPI + MySQL (main.py)
from datetime import date, datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def run(sql, args=()):   # SELECT -> list of rows | INSERT/UPDATE -> (rows changed, new id). Set your MySQL password below.
    with contextlib.closing(pymysql.connect(host="localhost", user="root", password="12345", database="flight_booking", cursorclass=pymysql.cursors.DictCursor, autocommit=True)) as db, db.cursor() as cur:
        cur.executemany(sql, args) if isinstance(args, list) else cur.execute(sql, args)
        if not cur.description: return cur.rowcount, cur.lastrowid
        return [{k: (datetime.min + v).strftime("%H:%M:%S") if isinstance(v, timedelta) else v for k, v in r.items()} for r in cur.fetchall()]  # TIME -> "06:30:00"
def setup():   # first run only: creates tables + 45 days of sample flights
    run("CREATE TABLE IF NOT EXISTS flights (id INT AUTO_INCREMENT PRIMARY KEY, flight_number VARCHAR(10), airline VARCHAR(50), source VARCHAR(50), destination VARCHAR(50), departure_date DATE, departure_time TIME, arrival_time TIME, price DECIMAL(10,2), total_seats INT, available_seats INT)")
    run("CREATE TABLE IF NOT EXISTS bookings (id INT AUTO_INCREMENT PRIMARY KEY, booking_ref VARCHAR(10) UNIQUE, flight_id INT, contact_email VARCHAR(120), contact_phone VARCHAR(20), total_price DECIMAL(10,2), status VARCHAR(15), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
    run("CREATE TABLE IF NOT EXISTS passengers (id INT AUTO_INCREMENT PRIMARY KEY, booking_id INT, name VARCHAR(100), age INT, gender VARCHAR(10))")
    if run("SELECT id FROM flights LIMIT 1"): return
    cities, slots = ["Delhi", "Mumbai", "Bangalore", "Chennai", "Hyderabad", "Kolkata"], [("06:30", "IndiGo", "6E"), ("13:15", "Air India", "AI"), ("19:45", "SpiceJet", "SG")]
    rows = [(f"{code}{random.randint(100, 999)}", airline, src, dst, date.today() + timedelta(days=day), t, (datetime.strptime(t, "%H:%M") + timedelta(minutes=mins)).strftime("%H:%M"), price, 60, 60)
            for a, b in itertools.combinations(cities, 2) for mins, price in [(random.randint(60, 175), random.randint(25, 68) * 100)]
            for src, dst in [(a, b), (b, a)] for day in range(45) for t, airline, code in slots]
    run("INSERT INTO flights (flight_number, airline, source, destination, departure_date, departure_time, arrival_time, price, total_seats, available_seats) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
setup()

@app.get("/api/cities")
def list_cities(): return [r["source"] for r in run("SELECT DISTINCT source FROM flights ORDER BY source")]
@app.get("/api/flights")
def search_flights(source: str, destination: str, travel_date: date, passengers: int = 1):
    if source == destination or travel_date < date.today(): raise HTTPException(400, "Choose two different cities and a future date")
    return run("SELECT * FROM flights WHERE source=%s AND destination=%s AND departure_date=%s AND available_seats>=%s ORDER BY departure_time", (source, destination, travel_date, passengers))

def full(where, args):   # bookings + their flight + passengers (the shape the frontend needs)
    out = run("SELECT * FROM bookings WHERE " + where + " ORDER BY id DESC", args)
    for b in out:
        b["flight"], b["passengers"] = run("SELECT * FROM flights WHERE id=%s", (b["flight_id"],))[0], run("SELECT id, name, age, gender FROM passengers WHERE booking_id=%s", (b["id"],))
    return out
@app.post("/api/bookings", status_code=201)
def book(data: dict):
    n, f = len(data["passengers"]), run("SELECT * FROM flights WHERE id=%s", (data["flight_id"],))
    if not f or f[0]["departure_date"] < date.today(): raise HTTPException(404, "Flight not found or already departed")
    if not n or not run("UPDATE flights SET available_seats=available_seats-%s WHERE id=%s AND available_seats>=%s", (n, f[0]["id"], n))[0]: raise HTTPException(400, "Not enough seats left on this flight")
    bid = run("INSERT INTO bookings (booking_ref, flight_id, contact_email, contact_phone, total_price, status) VALUES (%s,%s,%s,%s,%s,'CONFIRMED')", (f"FB{random.randint(100000, 999999)}", f[0]["id"], data["contact_email"].strip().lower(), data["contact_phone"], f[0]["price"] * n))[1]
    run("INSERT INTO passengers (booking_id, name, age, gender) VALUES (%s,%s,%s,%s)", [(bid, p["name"], p["age"], p["gender"]) for p in data["passengers"]])
    return full("id=%s", (bid,))[0]
@app.get("/api/bookings/{ref}")
def one(ref: str):
    b = full("booking_ref=%s", (ref.strip().upper(),))
    if not b: raise HTTPException(404, "Booking not found")
    return b[0]
@app.get("/api/bookings")
def find_bookings(email: str = "", ref: str = ""):
    e, r = email.strip().lower(), ref.strip().upper()
    if not e and not r: raise HTTPException(400, "Please provide an email or a booking reference")
    return full("(%s='' OR contact_email=%s) AND (%s='' OR booking_ref=%s)", (e, e, r, r))
@app.post("/api/bookings/{ref}/cancel")
def cancel(ref: str):
    b = one(ref)
    if b["status"] == "CANCELLED": raise HTTPException(400, "This booking is already cancelled")
    run("UPDATE bookings b JOIN flights f ON f.id = b.flight_id SET b.status='CANCELLED', f.available_seats = f.available_seats + %s WHERE b.id=%s", (len(b["passengers"]), b["id"]))
    return {**b, "status": "CANCELLED"}