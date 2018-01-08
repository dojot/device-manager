from datetime import datetime
import re
import sqlalchemy
from flask_sqlalchemy import SQLAlchemy
from app import app
from utils import HTTPRequestError
from conf import CONFIG

app.config['SQLALCHEMY_DATABASE_URI'] = CONFIG.get_db_url()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


class DeviceTemplate(db.Model):
    __tablename__ = 'templates'

    id = db.Column(db.Integer, db.Sequence('template_id'), primary_key=True)
    label = db.Column(db.String(128), nullable=False)
    created = db.Column(db.DateTime, default=datetime.now)
    updated = db.Column(db.DateTime, onupdate=datetime.now)

    attrs = db.relationship("DeviceAttr", back_populates="template", lazy='joined', cascade="delete")
    devices = db.relationship("Device", secondary='device_template', back_populates="templates")

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

    id = db.Column(db.String(4), unique=True, nullable=False, primary_key=True)
    label = db.Column(db.String(128), nullable=False)
    created = db.Column(db.DateTime, default=datetime.now)
    updated = db.Column(db.DateTime, onupdate=datetime.now)

    # template_id = db.Column(db.Integer, db.ForeignKey('templates.id'), nullable=False)
    templates = db.relationship("DeviceTemplate", secondary='device_template', back_populates="devices")

    persistence = db.Column(db.String(128))

    def __repr__(self):
        return "<Device(label='%s')>" % self.label


class DeviceTemplateMap(db.Model):
    __tablename__ = 'device_template'
    device_id = db.Column(db.String(4), db.ForeignKey('devices.id'), primary_key=True, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey('templates.id'), primary_key=True, index=True)


def assert_device_exists(device_id):
    try:
        return Device.query.filter_by(id=device_id).one()
    except sqlalchemy.orm.exc.NoResultFound:
        raise HTTPRequestError(404, "No such device: %s" % device_id)


def assert_template_exists(template_id):
    try:
        return DeviceTemplate.query.filter_by(id=template_id).one()
    except sqlalchemy.orm.exc.NoResultFound:
        raise HTTPRequestError(404, "No such template: %s" % template_id)


def assert_device_relation_exists(device_id, template_id):
    try:
        return DeviceTemplateMap.query.filter_by(device_id=device_id, template_id=template_id).one()
    except sqlalchemy.orm.exc.NoResultFound:
        raise HTTPRequestError(404, "Device %s is not associated with template %s" % (device_id, template_id))


def handle_consistency_exception(error):
    # message = error.message.replace('\n','')
    message = re.sub(r"(^\(.*?\))|\n", "", error.message)
    raise HTTPRequestError(400, message)
