# 'places' in radio.db adapted from https://www.maxmind.com/en/free-world-cities-database

import os
import re
import string

from flask import Flask, jsonify, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from flask_jsglue import JSGlue
from marshmallow import Schema, fields
from passlib.apps import custom_app_context as pwd_context

from tempfile import mkdtemp

from helpers import *

# configure application
app = Flask(__name__)
JSGlue(app)

# configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Flask-SQLAlchemy
app.config.from_pyfile('config.cfg')
db = SQLAlchemy(app)


### MODELS ###

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True)
    password = db.Column(db.String(30))

    favourites = db.relationship('Favourite', backref='user', lazy='dynamic')

    def __init__(self, username, password):
        self.username = username
        self.password = password

    def __repr__(self):
        return '<User %r>' % self.username


class Place(db.Model):
    __tablename__ = 'places'

    id = db.Column(db.Integer, primary_key=True)
    city = db.Column(db.String(60))
    state = db.Column(db.String(2))
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)

    stations = db.relationship('Station', backref='place')

    def __init__(self, city, state, lat, lng):
        self.city = city
        self.state = state
        self.lat = lat
        self.lng = lng

    def __repr__(self):
        return '<Place %r>' % self.city


class Station(db.Model):
    __tablename__ = 'stations'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30))
    call = db.Column(db.String(30))
    place_id = db.Column(db.Integer, db.ForeignKey('places.id'))
    url_stream = db.Column(db.String(30))
    url_site = db.Column(db.String(30))
    freq = db.Column(db.String(30))
    power = db.Column(db.Integer)

    favourites = db.relationship('Favourite', backref='station', lazy='dynamic')

    def __init__(self, name, call, place_id, url_stream, url_site, freq, power):
        self.name = name
        self.call = call
        self.place_id = place_id
        self.url_stream = url_stream
        self.url_site = url_site
        self.freq = freq
        self.power = power

    def __repr__(self):
        return '<Station %r>' % self.name


class Favourite(db.Model):
    __tablename__ = 'favourites'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id'))

    def __init__(self, user_id, station_id):
        self.user_id = user_id
        self.station_id = station_id

    def __repr(self):
        return '<Favourite %r>' % self.id


### SCHEMA ###

class PlaceSchema (Schema):
    place_id = fields.Int(dump_only=True)
    city = fields.Str()
    state = fields.Str()
    lat = fields.Float()
    lng = fields.Float()

class StationSchema (Schema):
    station_id = fields.Int(dump_only=True)
    name = fields.Str()
    call = fields.Str()
    url_site = fields.Str()
    url_stream = fields.Str()
    freq = fields.Str()
    power = fields.Str()
    place = fields.Nested(PlaceSchema)

geo_stations = StationSchema(many=True)


# ensure responses aren't cached
if app.config["DEBUG"]:
    @app.after_request
    def after_request(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Expires"] = 0
        response.headers["Pragma"] = "no-cache"
        return response


### CUSTOM FUNCTIONS ###

def get_username():
    """Returns username from userid """

    if session.get("user_id") is None:
        username = ""
    else:
        user_id = session.get("user_id")
        user = User.query.filter(User.id==user_id).first()
        username = user.username

    return username


### ROUTES ###

@app.route("/")
def index():
    """Default map rendered"""

    # check Google API key set
    if not os.environ.get("API_KEY"):
        raise RuntimeError("API_KEY not set")

    # check for user logged in
    if "user_id" in session:
        favourites = Favourite.query.filter(Favourite.user_id==session["user_id"]).all()
    else:
        favourites = []

    return render_template("index.html", key=os.environ.get("API_KEY"), username=get_username(), favourites=favourites)


# *** this route draws from CS50 PSET8 distribution code *** #
@app.route("/search")
def search():
    """Search for places that match query."""

    # no search query retrieved
    if not request.args.get("q"):
        raise RuntimeError("missing search parameter q")

    # store search query
    q = request.args.get("q")

    # remove any punctuation
    for punc in string.punctuation:
        q = q.replace(punc, '')

    # prevents http 500 error when string started with punctuation
    if q == "":
        q = "xyz"

    # split multi-word query
    elements = []
    for word in q.split():
        # add to array, concat with SQL wildcard
        elements.append(word + '%')

    if len(elements) == 1:
        # assuming: city // state
        station_list = Station.query.join(Place).\
            filter(db.or_(Place.city.like(elements[0]), Place.state.like(elements[0]))).all()

        # assuming: name // call
        station_list += Station.query.\
            filter(db.or_(Station.name.like(elements[0]), Station.call.like(elements[0]))).all()

    elif len(elements) == 2:
        # assuming: city city
        station_list = Station.query.join(Place).\
            filter(Place.city.like(elements[0]+elements[1])).all()

        # assuming: city, state
        station_list += Station.query.join(Place).\
            filter(db.and_(Place.city.like(elements[0]), Place.state.like(elements[1]))).all()

        # assuming: name / call, city / state
        station_list += Station.query.join(Place).\
            filter(db.and_(
                db.or_(Station.name.like(elements[0]), Station.call.like(elements[0])),
                db.or_(Place.city.like(elements[1]), Place.state.like(elements[1])))).all()

    elif len(elements) == 3:
        # assuming: city city, state
        station_list = Station.query.join(Place).\
            filter(db.and_(Place.city.like(elements[0]+elements[1]), Place.state.like(elements[2]))).all()

        # assuming: name / call, city city
        station_list += Station.query.join(Place).\
            filter(db.and_(
                db.or_(Station.name.like(elements[0]), Station.call.like(elements[0])),
                Place.city.like(elements[1]+elements[2]))).all()

        # assuming: name / call, city, state
        station_list += Station.query.join(Place).\
            filter(db.and_(
                db.or_(Station.name.like(elements[0]), Station.call.like(elements[0])),
                db.and_(Place.city.like(elements[1]), Place.state.like(elements[2])))).all()

    elif len(elements) == 4:
        # assuming: name / call, city city, state
        station_list = Station.query.join(Place).\
            filter(db.and_(
                db.or_(Station.name.like(elements[0]), Station.call.like(elements[0])),
                db.and_(Place.city.like(elements[1]+elements[2]), Place.state.like(elements[3])))).all()

    # serialize thequery set
    result = geo_stations.dump(station_list)

    return jsonify(result.data)


# *** this route draws heavily from CS50 PSET8 distribution code *** #
@app.route("/update")
def update():
    """Get stations within map window view """

    # ensure parameters are present
    if not request.args.get("sw"):
        raise RuntimeError("missing sw")
    if not request.args.get("ne"):
        raise RuntimeError("missing ne")

    # ensure parameters are in lat,lng format
    if not re.search("^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$", request.args.get("sw")):
        raise RuntimeError("invalid sw")
    if not re.search("^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$", request.args.get("ne")):
        raise RuntimeError("invalid ne")

    # explode southwest corner into two variables
    (sw_lat, sw_lng) = [float(s) for s in request.args.get("sw").split(",")]

    # explode northeast corner into two variables
    (ne_lat, ne_lng) = [float(s) for s in request.args.get("ne").split(",")]

    # find stations within view
    if (sw_lng <= ne_lng):
        # doesn't cross the antimeridian

        stations = Station.query.join(Place).\
            filter(db.and_(
                sw_lat <= Place.lat, Place.lat <= ne_lat,(db.and_(
                sw_lng <= Place.lng, Place.lng <= ne_lng)))).all()

    else:
        # crosses the antimeridian

        stations = Station.query.join(Place).\
            filter(db.and_(
                sw_lat <= Place.lat, Place.lat <= ne_lat,(db.or_(
                sw_lng <= Place.lng, Place.lng <= ne_lng)))).all()

    result = geo_stations.dump(stations)

    return jsonify(result.data)


@app.route("/lookup")
def lookup():
    """Return JSON of stations for marker clicked"""
    """ OR station info for current selection"""

    # check which arguements are present
    if request.args.get("city") and request.args.get("state"):
        # get all stations for a location

        city = request.args.get("city")
        state = request.args.get("state")

        station_list = Station.query.join(Place).\
            filter(Place.city == city, Place.state == state).all()

        result = geo_stations.dump(station_list)

    if request.args.get("stream"):
        # get station for specified url

        url = request.args.get("stream")

        station_list = Station.query.join(Place).\
            filter(Station.url_stream == url).all()

        result = geo_stations.dump(station_list)

    return jsonify(result.data)


@app.route("/stations")
def stations():

    # get all stations
    stations = Station.query

    # sort parameter present
    if request.args.get("sort"):

        sort = request.args.get("sort")

        if sort == "place":
            stations = stations.join(Place).order_by('state', 'city').all()
        else:
            stations = stations.order_by(sort).all()

    # default sort by place
    else:
        stations = stations.join(Place).order_by('state', 'city').all()

    return render_template("stations.html", username=get_username(), stations=stations)


@app.route("/favourite", methods=["GET", "POST"])
@login_required
def favourite():
    """Add, delete, or view favourites"""

    # user is adding or deleting a favourite
    if request.method == "POST":

        # user is adding a station from 'stations.html'
        if request.form.get("add"):

            # max limit of 5 favourites per user
            if len(Favourite.query.filter(Favourite.user_id==session["user_id"]).all()) > 4:

                return redirect(url_for("stations", error="limit"))

            # remember id of station to add
            station_id = request.form.get("add")

            # check user hasn't already favourited station
            if(Favourite.query.filter(Favourite.user_id==session["user_id"],Favourite.station_id==station_id).first()):

                return redirect(url_for("stations", error="taken"))

            # add favourite to db for user
            addFav = Favourite(user_id=session["user_id"],station_id=station_id)
            db.session.add(addFav)
            db.session.commit()

            return redirect(url_for("stations", success=True))

        # user is deleting a station from 'favourites.html'
        elif request.form.get("delete"):

            station_id = request.form.get("delete")

            delFav = Favourite.query.filter(Favourite.user_id==session["user_id"],Favourite.station_id==station_id).first()
            db.session.delete(delFav)
            db.session.commit()

            return redirect(url_for("favourite", deleted=True))

    # user is viewing favourites via GET
    else:
        favourites = Favourite.query.filter(Favourite.user_id==session["user_id"]).all()

        return render_template("favourites.html", username=get_username(), favourites=favourites)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    # page accessed via POST
    if request.method == "POST":

        # safety checks if browser doesn't support JS checks
        if not request.form.get("username"):
            return redirect(url_for("register", error="username"))
        if not request.form.get("password"):
            return redirect(url_for("register", error="password"))
        if not request.form.get("confirmation"):
            return redirect(url_for("register", error="confirmation"))
        if request.form.get("password") != request.form.get("confirmation"):
            return redirect(url_for("register", error="mismatch"))

        # remember username
        username = request.form.get("username")

        # check if name is taken
        if User.query.filter(User.username == username).all():
            return redirect(url_for("register", error="taken"))

        # hash the password
        hash = pwd_context.encrypt(request.form.get("password"))

        # add new user to db
        new = User(username=username, password=hash)
        db.session.add(new)
        db.session.commit()

        # add new user to session by id
        session["user_id"] = User.query.filter(User.username == username).first().id

        # redirect user to home page
        return redirect(url_for("index"))

    # page accessed via GET
    else:
        return render_template("register.html")


@app.route("/login", methods=["POST"])
def login():
    """Log user in"""

    # forget any user_id
    session.clear()

    # ensure username was submitted
    if not request.form.get("username"):
        return redirect(url_for("index", error=True))
    # ensure password was submitted
    elif not request.form.get("password"):
        return redirect(url_for("index", error=True))

    # query database for username
    user = User.query.filter(User.username == request.form.get("username")).first()

    # user doesn't exist or paswords don't match, redirect
    if not user or not pwd_context.verify(request.form.get("password"), user.password):
        if request.form.get("submit") == "/":
            return redirect(url_for("index", error=True))
        else:
            return redirect(url_for(request.form.get("submit").strip('/'), error=True))

    # user exists and passwords match, remember user
    session["user_id"] = user.id

    # redirect user to the page from which they submitted the login form
    if request.form.get("submit") == "/":
        return redirect(url_for("index"))
    else:
        return redirect(url_for(request.form.get("submit").strip('/')))


@app.route("/logout")
def logout():
    """Log user out"""

    # forget any user_id
    session.clear()

    # redirect user to login form
    return redirect(url_for("index"))


@app.route("/about", methods=["GET"])
def about():
    """About page"""

    return render_template("about.html", username=get_username())
