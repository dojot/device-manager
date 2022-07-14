import base64
import logging
import json

import requests
from kafka import KafkaProducer
from kafka.errors import KafkaTimeoutError

from DeviceManager.conf import CONFIG
from DeviceManager.Logger import Log
from datetime import datetime
import time


LOGGER = Log().color_log()


class DeviceEvent:
    CREATE = "create"
    UPDATE = "update"
    REMOVE = "remove"
    CONFIGURE = "configure"
    TEMPLATE = "template.update"


class NotificationMessage:
    event = ""
    data = None
    meta = None

    def __init__(self, ev, d, m):
        self.event = ev
        self.data = d
        self.meta = m

    def to_json(self):
        return {"event": self.event, "data": self.data, "meta": self.meta}


class KafkaNotifier:

    def __init__(self):
        self.kafka_address = CONFIG.kafka_host + ':' + CONFIG.kafka_port
        self.kf_prod = None
        
        self.kf_prod = KafkaProducer(value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                                bootstrap_servers=self.kafka_address)

        # Maps services to their managed topics
        self.topic_map = {}

    def get_topic(self, service, subject):
        return "{}.{}".format(service, subject);

    def send_notification(self, event, device, meta):
        # TODO What if Kafka is not yet up?

        full_msg = NotificationMessage(event, device, meta)
        try:
            topic = self.get_topic(meta['service'], CONFIG.subject)
            LOGGER.debug(f" topic for {CONFIG.subject} is {topic}")
            if topic is None:
                LOGGER.error(f" Failed to retrieve named topic to publish to")

            self.kf_prod.send(topic, full_msg.to_json())
            self.kf_prod.flush()
        except KafkaTimeoutError:
            LOGGER.error(f" Kafka timed out.")

    def send_raw(self, raw_data, tenant):
        try:
            topic = self.get_topic(tenant, CONFIG.subject)
            if topic is None:
                LOGGER.error(f" Failed to retrieve named topic to publish to")
            self.kf_prod.send(topic, raw_data)
            self.kf_prod.flush()
        except KafkaTimeoutError:
            LOGGER.error(f" Kafka timed out.")
