#
#
#

import RPi.GPIO as GPIO
import sqlalchemy
import time

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import Sequence
from sqlalchemy import String

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


POWER_STATES = {
    0: 'off',
    1: 'on',
}

SHORT_PRESS = 2
LONG_PRESS = 10


Base = declarative_base()


def relay_control(pin, duration):
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)
    time.sleep(duration)
    GPIO.output(pin, GPIO.HIGH)
    GPIO.cleanup()


def read_relay(pin):
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    value = GPIO.input(pin)
    GPIO.cleanup()
    return value


class Computer(Base):
    __tablename__ = 'computers'

    id = Column(Integer, Sequence('comp_id_seq'), primary_key=True)
    name = Column(String(50))
    power_control_pin = Column(Integer)
    power_state_pin = Column(Integer)

    def save(self):
        """Persists the instance to the database."""
        session = _get_session()
        session.add(self)
        session.commit()

    def get_power_state(self):
        current_state = read_relay(self.power_state_pin)
        return POWER_STATES[current_state]

    def poweron(self):
        if self.get_power_state() == 'on':
            return
        relay_control(self.power_control_pin, SHORT_PRESS)

    def poweroff(self):
        if self.get_power_state() == 'off':
            return
        relay_control(self.power_control_pin, LONG_PRESS)

    def is_valid_action(self, action):
        return action in ['powerstate', 'on', 'off', 'hardoff', 'reset']

    def __repr__(self):
        return ("<Computer(name='%s', power_control_pin=%s, "
                "power_state_pin='%s')>" %
                (self.name, self.power_control_pin, self.power_state_pin))


# TODO(wolsen) this is really ugly. Should be done as part of
# an init step rather than just doing this whenever the object
# is imported.
__engine__ = sqlalchemy.create_engine('sqlite:///computers.db')
Session = sessionmaker(bind=__engine__)
__session__ = None
Base.metadata.create_all(__engine__)


def _get_session():
    global __session__
    global __engine__
    if __session__ is None:
        __session__ = Session()
    return __session__


def get_computer(name):
    """Retrieves the Computer model from the database."""
    session = _get_session()
    computer = session.query(Computer).filter_by(name=name).first()
    return computer


def get_computers():
    session = _get_session()
    return [c for c in session.query(Computer).all()]

