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
        if service in self.topic_map.keys():
            if subject in self.topic_map[service].keys():
                return self.topic_map[service][subject]

        target = "{}/topic/{}".format(CONFIG.data_broker, subject)
        userinfo = {
            "username": "device-manager",
            # "service": service
            "iss": "http://localhost:8000/auth/realms/" + service
        }

        jwt = "{}.{}.{}".format(base64.b64encode("model".encode()).decode(),
                                base64.b64encode(json.dumps(
                                    userinfo).encode()).decode(),
                                base64.b64encode("signature".encode()).decode())

        response = requests.get(target, headers={"authorization": jwt})
        if 200 <= response.status_code < 300:
            payload = response.json()
            if self.topic_map.get(service, None) is None:
                self.topic_map[service] = {}
            self.topic_map[service][subject] = payload['topic']
            return payload['topic']
        return None

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
