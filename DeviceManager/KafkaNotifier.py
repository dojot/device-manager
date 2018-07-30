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


timeStamp = datetime.fromtimestamp(time.time()).strftime('%d/%m/%Y:%H:%M:%S')
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


kafka_address = CONFIG.kafka_host + ':' + CONFIG.kafka_port
kf_prod = KafkaProducer(value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                        bootstrap_servers=kafka_address)

# Maps services to their managed topics
topic_map = {}

def get_topic(service, subject):
    if service in topic_map.keys():
        if subject in topic_map[service].keys():
            return topic_map[service][subject]

    target = "{}/topic/{}".format(CONFIG.data_broker, subject)
    userinfo = {
        "username": "device-manager",
        "service": service
    }

    jwt = "{}.{}.{}".format(base64.b64encode("model".encode()).decode(),
                            base64.b64encode(json.dumps(userinfo).encode()).decode(),
                            base64.b64encode("signature".encode()).decode())

    response = requests.get(target, headers={"authorization": jwt})
    if 200 <= response.status_code < 300:
        payload = response.json()
        if topic_map.get(service, None) is None:
            topic_map[service] = {}
        topic_map[service][subject] = payload['topic']
        return payload['topic']
    return None


def send_notification(event, device, meta):
    # TODO What if Kafka is not yet up?

    full_msg = NotificationMessage(event, device, meta)
    try:
        topic = get_topic(meta['service'], CONFIG.subject)
        LOGGER.debug(f"[{timeStamp}] |{__name__}| topic for {CONFIG.subject} is {topic}")
        if topic is None:
            LOGGER.error(f"[{timeStamp}] |{__name__}| Failed to retrieve named topic to publish to")

        kf_prod.send(topic, full_msg.to_json())
        kf_prod.flush()
    except KafkaTimeoutError:
        LOGGER.error(f"[{timeStamp}] |{__name__}| Kafka timed out.")

def send_raw(raw_data, tenant):
    try:
        topic = get_topic(tenant, CONFIG.subject)
        if topic is None:
            LOGGER.error(f"[{timeStamp}] |{__name__}| Failed to retrieve named topic to publish to")
        kf_prod.send(topic, raw_data)
        kf_prod.flush()
    except KafkaTimeoutError:
        LOGGER.error(f"[{timeStamp}] |{__name__}| Kafka timed out.")
        