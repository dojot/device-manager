from datetime import datetime
import sqlalchemy
from flask_sqlalchemy import SQLAlchemy
from app import app
from utils import HTTPRequestError

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://postgres@postgres/dojot_devm'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class DeviceTemplate(db.Model):
    __tablename__ = 'templates'

    id = db.Column(db.Integer, db.Sequence('template_id'), primary_key=True)
    label = db.Column(db.String(128), nullable=False)
    created = db.Column(db.DateTime, default=datetime.now)
    updated = db.Column(db.DateTime, onupdate=datetime.now)

    attrs = db.relationship("DeviceAttr", back_populates="template", lazy='joined', cascade="delete")

    def __repr__(self):
        return "<Template(label='%s')>" % self.label

class DeviceAttr(db.Model):
    __tablename__ = 'attrs'

    id = db.Column(db.Integer, db.Sequence('attr_id'), primary_key=True)
    label = db.Column(db.String(128), nullable=False)
    created = db.Column(db.DateTime, default=datetime.now)
    updated = db.Column(db.DateTime, onupdate=datetime.now)

    type = db.Column(db.String(32), nullable=False)
    value_type = db.Column(db.String(32), nullable=False)
    static_value = db.Column(db.String(128))

    template_id = db.Column(db.Integer, db.ForeignKey('templates.id'), nullable=False)
    template = db.relationship("DeviceTemplate", back_populates="attrs")

    def __repr__(self):
        return "<Attr(label='%s', type='%s', value_type='%s')>" % (
            self.label, self.type, self.value_type)

class Device(db.Model):
    __tablename__ = 'devices'

    device_id = db.Column(db.String(4), unique=True, nullable=False, primary_key=True)
    label = db.Column(db.String(128), nullable=False)
    created = db.Column(db.DateTime, default=datetime.now)
    updated = db.Column(db.DateTime, onupdate=datetime.now)

    protocol = db.Column(db.String(32), nullable=False)
    frequency = db.Column(db.Integer, default=2000)

    template_id = db.Column(db.Integer, db.ForeignKey('templates.id'), nullable=False)
    template = db.relationship("DeviceTemplate")

    persistence = db.Column(db.String(128))

    def __repr__(self):
        return "<Device(label='%s', template='%s', protocol='%s')>" % (
            self.label, self.template, self.protocol)


def assert_device_exists(device_id):
    try:
        return Device.query.filter_by(device_id=device_id).one()
    except sqlalchemy.orm.exc.NoResultFound:
        raise HTTPRequestError(404, "No such device: %s" % device_id)

def assert_template_exists(template_id):
    try:
        return DeviceTemplate.query.filter_by(id=template_id).one()
    except sqlalchemy.orm.exc.NoResultFound:
        raise HTTPRequestError(404, "No such template: %s" % template_id)
